import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.ai import DispatchBriefing, generate_structured


class CoreSmokeTests(TestCase):
    def test_home_renders_with_global_htmx_csrf_header_and_health_link(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "X-CSRFToken")
        self.assertContains(response, "KGOC Marine Fleet")
        self.assertContains(response, reverse("core:health"))

    @override_settings(GEMINI_MODEL="gemini-4-hydrogen")
    def test_health_and_healthz_report_ok_database_and_model(self):
        for url_name in ("core:health", "core:healthz"):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["database"], "sqlite3")
            self.assertIn("ai_configured", payload)
            self.assertEqual(payload["gemini_model"], "gemini-4-hydrogen")

    @override_settings(GEMINI_API_KEY="")
    def test_generate_structured_handles_missing_api_key_gracefully(self):
        result, error = generate_structured(
            prompt="Summarize vessel utilization.",
            response_schema=DispatchBriefing,
        )
        self.assertIsNone(result)
        self.assertIsNotNone(error)
        self.assertIn("GEMINI_API_KEY", error)

    @override_settings(GEMINI_API_KEY="test-key", GEMINI_MODEL="gemini-4-hydrogen")
    @patch("apps.core.ai.genai.Client")
    def test_generate_structured_uses_interactions_api_without_temperature(self, mock_client_cls):
        expected = DispatchBriefing(
            executive_summary="Merge two half-empty runs.",
            recommended_actions=["Consolidate Trip A and Trip B"],
            safety_flags=[],
            estimated_impact_note="Saves 1 trip and 420 L fuel.",
        )
        mock_client = MagicMock()
        mock_client.interactions.create.return_value = SimpleNamespace(
            output_text=expected.model_dump_json(),
            steps=[],
        )
        mock_client_cls.return_value = mock_client

        result, error = generate_structured(
            prompt="Summarize vessel utilization.",
            response_schema=DispatchBriefing,
            system_instruction="Be concise.",
        )

        self.assertIsNone(error)
        self.assertEqual(result, expected)
        kwargs = mock_client.interactions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gemini-4-hydrogen")
        self.assertEqual(kwargs["response_format"]["mime_type"], "application/json")
        self.assertEqual(kwargs["generation_config"], {"thinking_level": "medium"})
        self.assertNotIn("temperature", kwargs["generation_config"])
        self.assertEqual(kwargs["system_instruction"], "Be concise.")

    @override_settings(GEMINI_API_KEY="test-key", GEMINI_MODEL="gemini-4-hydrogen")
    @patch("apps.core.ai.genai.Client")
    def test_generate_structured_strips_markdown_json_fences(self, mock_client_cls):
        expected = DispatchBriefing(
            executive_summary="Fenced output parsed cleanly.",
            recommended_actions=["Keep single standby boat"],
            safety_flags=["High swell warning"],
            estimated_impact_note="Saves 180 KWD.",
        )
        mock_client = MagicMock()
        mock_client.interactions.create.return_value = SimpleNamespace(
            output_text=f"```json\n{expected.model_dump_json()}\n```",
            steps=[],
        )
        mock_client_cls.return_value = mock_client

        result, error = generate_structured(
            prompt="Summarize fenced output.",
            response_schema=DispatchBriefing,
        )

        self.assertIsNone(error)
        self.assertEqual(result, expected)

    @override_settings(GEMINI_API_KEY="test-key", GEMINI_MODEL="gemini-4-hydrogen")
    @patch("apps.core.ai.genai.Client")
    def test_generate_structured_returns_error_on_sdk_exception(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.interactions.create.side_effect = RuntimeError("boom")
        mock_client_cls.return_value = mock_client

        result, error = generate_structured(
            prompt="Trigger SDK error.",
            response_schema=DispatchBriefing,
        )

        self.assertIsNone(result)
        self.assertEqual(error, "Gemini request failed: RuntimeError")

    def test_inspect_dataset_csv_and_multisheet_xlsx(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            csv_path = tmp_path / "trips.csv"
            xlsx_path = tmp_path / "fleet.xlsx"

            trips_df = pd.DataFrame(
                {
                    "trip_id": [f"T-{i:03d}" for i in range(1, 16)],
                    "vessel": ["Al-Khafji" if i % 2 == 0 else "Safaniya" for i in range(1, 16)],
                    "departure_time": [f"2026-11-{(i % 28) + 1:02d} 08:00" for i in range(1, 16)],
                    "fuel_liters": [400 + i * 10 for i in range(1, 16)],
                }
            )
            vessels_df = pd.DataFrame(
                {
                    "vessel_name": ["Al-Khafji", "Safaniya"],
                    "pax_capacity": [20, 18],
                }
            )

            trips_df.to_csv(csv_path, index=False)
            with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
                vessels_df.to_excel(writer, sheet_name="Vessels", index=False)
                trips_df.to_excel(writer, sheet_name="Trips", index=False)

            csv_out = io.StringIO()
            call_command("inspect_dataset", str(csv_path), stdout=csv_out)
            csv_text = csv_out.getvalue()
            self.assertIn("15 rows x 4 columns", csv_text)
            self.assertIn("sample_values", csv_text)
            self.assertIn("Date / Datetime Ranges", csv_text)
            self.assertIn("departure_time", csv_text)

            xlsx_all_out = io.StringIO()
            call_command("inspect_dataset", str(xlsx_path), stdout=xlsx_all_out)
            xlsx_all_text = xlsx_all_out.getvalue()
            self.assertIn("Sheets (2): Vessels, Trips", xlsx_all_text)
            self.assertIn("Sheet / Table: Vessels", xlsx_all_text)
            self.assertIn("2 rows x 2 columns", xlsx_all_text)
            self.assertIn("Sheet / Table: Trips", xlsx_all_text)
            self.assertIn("15 rows x 4 columns", xlsx_all_text)

            xlsx_single_out = io.StringIO()
            call_command("inspect_dataset", str(xlsx_path), sheet="Vessels", stdout=xlsx_single_out)
            xlsx_single_text = xlsx_single_out.getvalue()
            self.assertIn("Sheet / Table: Vessels", xlsx_single_text)
            self.assertNotIn("Sheet / Table: Trips", xlsx_single_text)
