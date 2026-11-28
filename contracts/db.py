"""SQLite database built from the bulletin JSON files, with a full-text index.

  python -m contracts.db        # (re)build data/contracts.db

Amounts, dates, contract numbers and the contracting activity come from the pattern-based fields
when found (exact), Claude's extraction otherwise. Contractor names and locations, contract type,
description and the role of each contract number come from Claude.
"""
import json
import sqlite3
import sys
from pathlib import Path

from . import config, parse, store

SCHEMA = """
CREATE TABLE bulletins (
    article_id   TEXT PRIMARY KEY,
    date         TEXT,              -- YYYY-MM-DD
    title        TEXT,
    url          TEXT,
    legend       TEXT               -- JSON: {"*": "Small business", ...}
);
CREATE TABLE announcements (
    id                    TEXT PRIMARY KEY,   -- <article_id>-<seq>
    article_id            TEXT,
    seq                   INTEGER,
    date                  TEXT,               -- bulletin date, YYYY-MM-DD
    award_date            TEXT,               -- only when stated and different, YYYY-MM-DD
    agency                TEXT,               -- bulletin heading: ARMY, NAVY, AIR FORCE, DEFENSE LOGISTICS AGENCY...
    kind                  TEXT,               -- announcement | correction
    action                TEXT,               -- new_contract | task_or_delivery_order | modification | option_exercise | multiple_award_pool | correction | other
    contractors           TEXT,               -- all awardee names, '; '-separated
    description           TEXT,               -- one line: what is bought
    contract_type         TEXT,
    value_usd             REAL,               -- announced value of this action, full dollars
    cumulative_value_usd  REAL,
    obligated_usd         REAL,               -- funds obligated at award; 0 = none; NULL = not stated
    funding_text          TEXT,
    completion_date       TEXT,               -- YYYY-MM-DD or YYYY-MM
    contracting_activity  TEXT,
    activity_code         TEXT,
    base_contract_number  TEXT,               -- normalized (no dashes)
    order_number          TEXT,
    modification_number   TEXT,
    fms                   INTEGER,            -- 1 if Foreign Military Sales are mentioned
    fms_countries         TEXT,               -- JSON array
    competition           TEXT,
    text                  TEXT,               -- full announcement text
    url                   TEXT
);
CREATE TABLE awardees (
    announcement_id   TEXT,
    position          INTEGER,
    name              TEXT,
    location          TEXT,
    contract_number   TEXT,                   -- normalized (no dashes)
    markers           TEXT,                   -- e.g. '*'
    marker_meanings   TEXT,                   -- e.g. 'Small business'
    small_business    INTEGER
);
CREATE TABLE contract_refs (
    contract_number   TEXT,                   -- normalized (no dashes)
    announcement_id   TEXT,
    role              TEXT                    -- award | base | order | mentioned
);
CREATE INDEX idx_ann_date ON announcements(date);
CREATE INDEX idx_ann_base ON announcements(base_contract_number);
CREATE INDEX idx_aw_name ON awardees(name);
CREATE INDEX idx_aw_ann ON awardees(announcement_id);
CREATE INDEX idx_refs ON contract_refs(contract_number);
CREATE VIRTUAL TABLE announcements_fts USING fts5(
    id UNINDEXED, agency, contractors, description, contracting_activity, text,
    content='announcements', content_rowid='rowid'
);
"""

# Shown to Claude when it writes SQL for the query app.
QUERYABLE_SCHEMA = """Tables built from war.gov daily contract announcements (one bulletin per business day):
bulletins(article_id TEXT PK, date TEXT 'YYYY-MM-DD', title, url, legend JSON)
announcements(id TEXT PK '<article_id>-<seq>', article_id, seq, date 'YYYY-MM-DD', award_date,
  agency TEXT -- upper case heading: 'ARMY','NAVY','AIR FORCE','DEFENSE LOGISTICS AGENCY',...
  kind TEXT -- 'announcement' or 'correction'
  action TEXT -- new_contract, task_or_delivery_order, modification, option_exercise, multiple_award_pool, correction, other
  contractors TEXT -- all awardee names joined with '; '
  description TEXT, contract_type TEXT,
  value_usd REAL, cumulative_value_usd REAL, obligated_usd REAL -- full US dollars, NULL if not stated
  funding_text TEXT, completion_date TEXT, contracting_activity TEXT, activity_code TEXT,
  base_contract_number TEXT, order_number TEXT, modification_number TEXT,
  fms INTEGER 0/1, fms_countries TEXT -- JSON array; use LIKE '%"Poland"%' or json_each()
  competition TEXT, text TEXT (full announcement), url TEXT)
awardees(announcement_id, position, name, location, contract_number, markers, marker_meanings, small_business 0/1)
contract_refs(contract_number, announcement_id, role) -- role: award | base | order | mentioned.
  Contract numbers are stored without dashes, upper case (W912BU-27-D-A004 -> W912BU27DA004).
  The history of a contract (award, orders, modifications) = all announcements whose contract_refs
  contain its number.
Virtual table announcements_fts (FTS5 over agency, contractors, description, contracting_activity, text);
  use: SELECT a.* FROM announcements_fts f JOIN announcements a ON a.rowid = f.rowid WHERE announcements_fts MATCH 'term'"""


def _norm(n):
    return parse.normalize_contract(n) if n else None


def _text(v):
    """Claude occasionally gives a list (['*']) where text is expected."""
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, list):
        return "".join(str(x) for x in v if x is not None) or None
    return str(v)


def _number(v):
    """Amounts occasionally come back as text ('64,059,000') or an object; keep only real numbers."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").replace("$", "").strip())
        except ValueError:
            return None
    return None


def flatten(b: dict, a: dict) -> dict:
    """One announcement as a flat record, merging pattern fields and Claude's extraction."""
    f = a.get("fields") or parse.fields(a["text"], b.get("legend"))
    e = dict(a.get("extracted") or {})
    for k in ("value_usd", "cumulative_value_usd", "obligated_usd"):
        e[k] = _number(e.get(k))
    for k in ("action", "contract_type", "description", "base_contract_number", "order_number",
              "modification_number", "competition", "award_date"):
        e[k] = _text(e.get(k))
    legend = b.get("legend") or {}

    def pick(*vals):
        return next((v for v in vals if v not in (None, "", [])), None)

    awardees = []
    for i, w in enumerate((w for w in e.get("awardees") or [] if isinstance(w, dict)), 1):
        marks = (_text(w.get("markers")) or "").strip() or None
        meanings = legend.get(marks) if marks else None
        awardees.append({"position": i, "name": (_text(w.get("name")) or "").rstrip(" ,*"), "location": _text(w.get("location")),
                         "contract_number": _norm(_text(w.get("contract_number"))), "markers": marks,
                         "marker_meanings": meanings or None,
                         "small_business": int("small business" in (meanings or "").lower())})
    countries = list(dict.fromkeys(c for c in (f.get("fms_countries") or []) + list(e.get("fms_countries") or [])
                                   if isinstance(c, str)))
    activity = f.get("contracting_activity") or {}
    action = e.get("action") or ("correction" if a["kind"] == "correction"
                                 else "modification" if f.get("is_modification") else None)
    mods = f.get("modification_numbers") or []
    rec = {
        "id": f"{b['article_id']}-{a['seq']}", "article_id": b["article_id"], "seq": a["seq"],
        "date": b.get("date"), "award_date": e.get("award_date"), "agency": a.get("agency"),
        "kind": a["kind"], "action": action,
        "contractors": "; ".join(w["name"] for w in awardees) or None,
        "description": e.get("description"), "contract_type": e.get("contract_type"),
        "value_usd": pick(f.get("value_usd"), e.get("value_usd")),
        "cumulative_value_usd": pick(f.get("cumulative_value_usd"), e.get("cumulative_value_usd")),
        "obligated_usd": pick(f.get("obligated_usd"), e.get("obligated_usd")),
        "funding_text": f.get("funding_text"), "completion_date": f.get("completion_date"),
        "contracting_activity": activity.get("name"), "activity_code": activity.get("code"),
        "base_contract_number": _norm(e.get("base_contract_number")),
        "order_number": _norm(e.get("order_number")),
        "modification_number": e.get("modification_number") or (mods[0] if mods else None),
        "fms": int(bool(f.get("fms") or countries)), "fms_countries": countries,
        "competition": e.get("competition"), "text": a["text"], "url": b.get("url"),
        "awardees": awardees,
    }
    refs = [(w["contract_number"], "award") for w in awardees if w["contract_number"]]
    refs += [(rec["base_contract_number"], "base"), (rec["order_number"], "order")]
    refs += [(n, "mentioned") for n in f.get("contract_numbers") or []]
    seen, rec["refs"] = set(), []
    for n, role in refs:
        if n and n not in seen:
            seen.add(n)
            rec["refs"].append((n, role))
    return rec


def build(bulletins_dir: str = config.BULLETINS_DIR, db_path: str = config.DB_PATH) -> int:
    """(Re)build the database from the JSON files. Returns the number of announcements."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)
    n = 0
    cols = ["id", "article_id", "seq", "date", "award_date", "agency", "kind", "action", "contractors",
            "description", "contract_type", "value_usd", "cumulative_value_usd", "obligated_usd",
            "funding_text", "completion_date", "contracting_activity", "activity_code",
            "base_contract_number", "order_number", "modification_number", "fms", "fms_countries",
            "competition", "text", "url"]
    for b in store.iter_bulletins(bulletins_dir):
        conn.execute("INSERT OR REPLACE INTO bulletins VALUES (?,?,?,?,?)",
                     (b["article_id"], b.get("date"), b.get("title"), b.get("url"), json.dumps(b.get("legend") or {})))
        for a in b["announcements"]:
            r = flatten(b, a)
            vals = [json.dumps(r[c]) if c == "fms_countries" else r[c] for c in cols]
            conn.execute(f"INSERT OR REPLACE INTO announcements ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
            conn.executemany("INSERT INTO awardees VALUES (?,?,?,?,?,?,?,?)",
                             [(r["id"], w["position"], w["name"], w["location"], w["contract_number"],
                               w["markers"], w["marker_meanings"], w["small_business"]) for w in r["awardees"]])
            conn.executemany("INSERT INTO contract_refs VALUES (?,?,?)", [(num, r["id"], role) for num, role in r["refs"]])
            n += 1
    conn.execute("INSERT INTO announcements_fts(announcements_fts) VALUES ('rebuild')")
    conn.commit()
    conn.close()
    tmp.replace(p)
    return n


if __name__ == "__main__":
    count = build()
    print(f"Built {config.DB_PATH} with {count} announcements.", file=sys.stderr)
