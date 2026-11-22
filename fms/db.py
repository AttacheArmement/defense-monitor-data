"""SQLite storage, with a full-text index for keyword search."""
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS notices (
    document_number      TEXT PRIMARY KEY,   -- Federal Register document number, e.g. 2026-17980
    title                TEXT,
    publication_date     TEXT,               -- YYYY-MM-DD
    citation             TEXT,               -- e.g. 91 FR 55551
    html_url             TEXT,
    pdf_url              TEXT,
    notice_type          TEXT,               -- new_sale | enhancement_upgrade | amendment | correction | other
    transmittal_number   TEXT,
    country              TEXT,               -- purchasing country or organization
    items_summary        TEXT,               -- short description of what is being sold
    major_defense_equipment TEXT,            -- JSON list of strings
    total_value_usd      REAL,               -- full dollars; NULL if not stated
    mde_value_usd        REAL,               -- full dollars; NULL if not stated
    prime_contractors    TEXT,               -- JSON list of strings
    date_to_congress     TEXT,               -- YYYY-MM-DD
    summary              TEXT,               -- 2-3 sentence plain-English summary
    raw_text             TEXT,
    extraction_json      TEXT,
    inserted_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_notices_pubdate ON notices(publication_date);
CREATE INDEX IF NOT EXISTS idx_notices_country ON notices(country);

CREATE VIRTUAL TABLE IF NOT EXISTS notices_fts USING fts5(
    document_number UNINDEXED, title, country, items_summary, summary, raw_text,
    content='notices', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS notices_ai AFTER INSERT ON notices BEGIN
    INSERT INTO notices_fts(rowid, document_number, title, country, items_summary, summary, raw_text)
    VALUES (new.rowid, new.document_number, new.title, new.country, new.items_summary, new.summary, new.raw_text);
END;
"""

# Shown to Claude when it writes SQL for the query app.
QUERYABLE_SCHEMA = """Table notices (one row per Federal Register arms sales notice):
  document_number TEXT PK, title TEXT, publication_date TEXT 'YYYY-MM-DD', citation TEXT,
  html_url TEXT, pdf_url TEXT,
  notice_type TEXT  -- one of: new_sale, enhancement_upgrade, amendment, correction, other
  transmittal_number TEXT, country TEXT, items_summary TEXT,
  major_defense_equipment TEXT -- JSON array of strings; use LIKE or json_each()
  total_value_usd REAL -- full US dollars, NULL if not stated
  mde_value_usd REAL, prime_contractors TEXT -- JSON array of strings
  date_to_congress TEXT 'YYYY-MM-DD', summary TEXT, raw_text TEXT (full notice text)
Virtual table notices_fts (FTS5 over title, country, items_summary, summary, raw_text);
  use: SELECT n.* FROM notices_fts f JOIN notices n ON n.rowid = f.rowid WHERE notices_fts MATCH 'term'"""


def build(notices_dir: str, db_path: str) -> int:
    """(Re)build the SQLite database from the JSON notice files. Returns the number of notices."""
    from . import store
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)
    n = 0
    for r in store.iter_notices(notices_dir):
        conn.execute(
            """INSERT OR REPLACE INTO notices (
                document_number, title, publication_date, citation, html_url, pdf_url,
                notice_type, transmittal_number, country, items_summary, major_defense_equipment,
                total_value_usd, mde_value_usd, prime_contractors, date_to_congress, summary,
                raw_text, extraction_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["document_number"], r.get("title"), r.get("publication_date"), r.get("citation"),
             r.get("html_url"), r.get("pdf_url"), r.get("notice_type"), r.get("transmittal_number"),
             r.get("country"), r.get("items_summary"),
             json.dumps(r.get("major_defense_equipment") or []),
             r.get("total_value_usd"), r.get("mde_value_usd"),
             json.dumps(r.get("prime_contractors") or []),
             r.get("date_to_congress"), r.get("summary"), r.get("raw_text"),
             json.dumps({k: v for k, v in r.items() if k != "raw_text"})))
        n += 1
    conn.commit()
    conn.close()
    tmp.replace(p)
    return n


def connect(path: str) -> sqlite3.Connection:
    """Read-only connection to a built database."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


if __name__ == "__main__":  # python -m fms.db  -> builds data/fms.db from the JSON files
    from . import config
    print(f"Built {config.DB_PATH} with {build(config.NOTICES_DIR, config.DB_PATH)} notices.")
