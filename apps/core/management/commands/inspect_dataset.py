"""Management command to quickly profile CSV/Excel datasets at hackathon kickoff."""

from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError

DATE_HINT_TOKENS = ("date", "time", "depart", "arriv")


def _truncate(value: object, limit: int = 40) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _format_sample_values(series: pd.Series, unique_count: int) -> str:
    non_null = series.dropna()
    if non_null.empty:
        return ""
    if unique_count <= 12:
        vals = [_truncate(v) for v in non_null.unique()[:8]]
        return ", ".join(vals)
    vals = [_truncate(v) for v in non_null.head(3).tolist()]
    return ", ".join(vals)


def _detect_date_ranges(df: pd.DataFrame) -> list[dict[str, object]]:
    date_rows: list[dict[str, object]] = []
    for col in df.columns:
        series = df[col]
        col_str = str(col)
        if pd.api.types.is_datetime64_any_dtype(series):
            parsed = series.dropna()
        elif (
            pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)
        ) and any(token in col_str.lower() for token in DATE_HINT_TOKENS):
            non_null = series.dropna()
            if non_null.empty:
                continue
            parsed = pd.to_datetime(non_null, errors="coerce").dropna()
            if len(parsed) / len(non_null) < 0.5:
                continue
        else:
            continue

        if parsed.empty:
            continue
        date_rows.append(
            {
                "column": col_str,
                "min": str(parsed.min()),
                "max": str(parsed.max()),
                "non_null": int(len(parsed)),
            }
        )
    return date_rows


class Command(BaseCommand):
    help = "Inspect a CSV or Excel dataset (sheets, schema, nulls, samples, date ranges, head)."

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str, help="Path to a .csv, .xlsx, or .xls file.")
        parser.add_argument(
            "--sheet",
            type=str,
            default=None,
            help="Specific Excel sheet name to inspect; defaults to all sheets.",
        )

    def _read_csv_with_fallback(self, path: Path) -> pd.DataFrame:
        try:
            return pd.read_csv(path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="latin-1")

    def _profile_dataframe(self, label: str, df: pd.DataFrame) -> None:
        self.stdout.write(self.style.SUCCESS(f"\n=== Sheet / Table: {label} ==="))
        self.stdout.write(f"Shape: {df.shape[0]} rows x {df.shape[1]} columns\n")

        self.stdout.write("=== Columns, Dtypes, Nulls, Unique Counts ===")
        summary_rows = []
        for col in df.columns:
            null_count = int(df[col].isna().sum())
            unique_count = int(df[col].nunique(dropna=True))
            summary_rows.append(
                {
                    "column": str(col),
                    "dtype": str(df[col].dtype),
                    "nulls": null_count,
                    "unique": unique_count,
                    "sample_values": _format_sample_values(df[col], unique_count),
                }
            )
        self.stdout.write(pd.DataFrame(summary_rows).to_string(index=False))

        date_rows = _detect_date_ranges(df)
        if date_rows:
            self.stdout.write("\n=== Date / Datetime Ranges ===")
            self.stdout.write(pd.DataFrame(date_rows).to_string(index=False))

        numeric_df = df.select_dtypes(include="number")
        if not numeric_df.empty:
            self.stdout.write("\n=== Numeric Summary ===")
            self.stdout.write(numeric_df.describe().round(2).to_string())

        self.stdout.write("\n=== First 5 Rows ===")
        self.stdout.write(df.head(5).to_string(index=False))

    def handle(self, *args, **options):
        path = Path(options["file_path"]).expanduser()
        if not path.exists():
            raise CommandError(f"Dataset file not found: {path}")

        suffix = path.suffix.lower()
        sheet_name = options.get("sheet")

        self.stdout.write(self.style.SUCCESS(f"Dataset: {path.name}"))

        if suffix == ".csv":
            tables = {"CSV": self._read_csv_with_fallback(path)}
        elif suffix in {".xlsx", ".xls"}:
            if sheet_name:
                try:
                    tables = {sheet_name: pd.read_excel(path, sheet_name=sheet_name)}
                except ValueError as exc:
                    raise CommandError(f"Sheet '{sheet_name}' not found in {path.name}: {exc}") from exc
            else:
                tables = pd.read_excel(path, sheet_name=None)
                self.stdout.write(f"Sheets ({len(tables)}): {', '.join(tables.keys())}")
        else:
            raise CommandError(f"Unsupported file extension '{suffix}'. Expected .csv, .xlsx, or .xls.")

        for label, df in tables.items():
            self._profile_dataframe(label, df)
