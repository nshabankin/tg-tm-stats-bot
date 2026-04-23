import csv
import io
import json
from pathlib import Path
from typing import Iterable, List


def _existing_text(path: Path) -> str:
    if not path.exists():
        return ''
    with path.open(encoding='utf-8', newline='') as existing_file:
        return existing_file.read()


def _write_text_if_changed(path: Path, content: str) -> bool:
    if _existing_text(path) == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as output_file:
        output_file.write(content)
    return True


def read_csv_rows(path: Path) -> List[dict]:
    with path.open(newline='', encoding='utf-8') as csv_file:
        return list(csv.DictReader(csv_file))


def write_csv(path: Path, rows: Iterable[dict], fieldnames: List[str]) -> bool:
    materialized_rows = list(rows)
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(materialized_rows)
    return _write_text_if_changed(path, buffer.getvalue())


def read_json(path: Path) -> dict:
    with path.open(encoding='utf-8') as json_file:
        return json.load(json_file)


def write_json(path: Path, payload: dict) -> bool:
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    return _write_text_if_changed(path, content)
