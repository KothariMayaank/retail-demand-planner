"""Read CSVs without coercing IDs or silently filling dates or missing values."""
from hashlib import sha256
from io import StringIO
import csv
import pandas as pd
from demand_planner.data.schemas import SCHEMAS
from demand_planner.domain import DatasetBundle


def load_csv_bundle(files: dict[str, bytes], source: str, max_upload_mb: int = 10) -> DatasetBundle:
    tables = {}
    digest = sha256()
    for name, content in sorted(files.items()):
        if name not in SCHEMAS:
            raise ValueError(f"Unknown input table: {name}")
        if len(content) > max_upload_mb * 1024 * 1024:
            raise ValueError(f"{name}.csv exceeds the {max_upload_mb} MB limit.")
        try:
            text = content.decode("utf-8-sig")
            reader = csv.reader(StringIO(text, newline=""), strict=True)
            header = next(reader)
            if not header or any(not column.strip() for column in header):
                raise ValueError("Column headers must not be blank.")
            if len(header) != len(set(header)):
                raise ValueError("Duplicate column headers are not allowed.")
            rows = []
            for row_number, row in enumerate(reader, start=2):
                if len(row) != len(header):
                    raise ValueError(f"Row {row_number} has {len(row)} fields; expected {len(header)}. "
                                     "Check commas, quotes and blank records.")
                rows.append(row)
            tables[name] = pd.DataFrame(rows, columns=header, dtype=str)
        except (UnicodeDecodeError, StopIteration, pd.errors.ParserError,
                pd.errors.EmptyDataError, csv.Error, ValueError) as exc:
            raise ValueError(f"Cannot read {name}.csv: {exc}") from exc
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(content)
    return DatasetBundle(tables=tables, source=source, fingerprint=digest.hexdigest())
