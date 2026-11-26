"""Bulletin storage: one pretty-printed JSON file per bulletin, organized by year.

The fetch step (run where war.gov is reachable) writes the bulletin's clean text: article ID, URL,
date, agency headings, the announcements in order and the marker legend. The processing step on
GitHub adds pattern-based fields and Claude's extraction to each announcement and records that
in "processed". The files are the source of truth; contracts.db builds SQLite from them.
"""
import json
from pathlib import Path


def path_for(bulletins_dir: str, article_id: str, date: str | None) -> Path:
    return Path(bulletins_dir) / ((date or "unknown")[:4]) / f"{article_id}.json"


def write(bulletins_dir: str, bulletin: dict) -> Path:
    p = path_for(bulletins_dir, bulletin["article_id"], bulletin.get("date"))
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(bulletin, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)  # atomic: never leaves a half-written file
    return p


def iter_paths(bulletins_dir: str):
    return sorted(Path(bulletins_dir).glob("*/*.json"))


def read(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def iter_bulletins(bulletins_dir: str):
    for p in iter_paths(bulletins_dir):
        yield read(p)


def known_ids(bulletins_dir: str) -> set:
    return {p.stem for p in iter_paths(bulletins_dir)}
