"""Notice storage: one pretty-printed JSON file per notice, organized by publication year.

Plain files keep the repo small (each day adds only the new notices), are readable on GitHub,
and are the source of truth. fms.db builds a SQLite database from them for querying.
"""
import json
from pathlib import Path

FIELDS_FROM_FR = ["document_number", "title", "publication_date", "citation", "html_url", "pdf_url"]
EXTRACTED_FIELDS = ["notice_type", "transmittal_number", "country", "items_summary",
                    "major_defense_equipment", "total_value_usd", "mde_value_usd",
                    "prime_contractors", "date_to_congress", "summary"]


def path_for(notices_dir: str, document_number: str, publication_date: str) -> Path:
    year = (publication_date or "unknown")[:4]
    return Path(notices_dir) / year / f"{document_number}.json"


def write_notice(notices_dir: str, meta: dict, raw_text: str, extracted: dict) -> dict:
    record = {k: meta.get(k) for k in FIELDS_FROM_FR}
    record.update({k: extracted.get(k) for k in EXTRACTED_FIELDS})
    for k in ("major_defense_equipment", "prime_contractors"):
        record[k] = record[k] or []
    record["raw_text"] = raw_text
    p = path_for(notices_dir, record["document_number"], record["publication_date"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)  # atomic: never leaves a half-written notice
    return record


def iter_notices(notices_dir: str):
    for p in sorted(Path(notices_dir).glob("*/*.json")):
        yield json.loads(p.read_text(encoding="utf-8"))


def known_document_numbers(notices_dir: str) -> set:
    return {p.stem for p in Path(notices_dir).glob("*/*.json")}


def latest_publication_date(notices_dir: str):
    dates = [r.get("publication_date") for r in iter_notices(notices_dir)]
    dates = [d for d in dates if d]
    return max(dates) if dates else None
