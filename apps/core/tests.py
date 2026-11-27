from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.ai import DispatchBriefing, generate_structured


class CoreSmokeTests(TestCase):
    def test_home_renders_with_global_htmx_csrf_header(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "X-CSRFToken")
        self.assertContains(response, "KGOC Marine Fleet")

    def test_healthz_reports_ok_and_database(self):
        response = self.client.get(reverse("core:healthz"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["database"], "sqlite3")
        self.assertIn("ai_configured", payload)

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
