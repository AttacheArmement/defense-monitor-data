"""Contracts-monitor settings."""
import os

BASE_URL = "https://www.war.gov/News/Contracts/"
# One JSON file per bulletin (committed): data/contracts/bulletins/<year>/<article_id>.json
BULLETINS_DIR = os.environ.get("CONTRACTS_BULLETINS_DIR") or "data/contracts/bulletins"
# SQLite database built from the JSON files for querying (not committed; rebuilt in seconds).
DB_PATH = os.environ.get("CONTRACTS_DB_PATH") or "data/contracts.db"

# Bulletins published before this date get pattern-based fields only, without Claude extraction
# (contractor names/locations, contract type, description). Empty = extract everything.
EXTRACT_SINCE = os.environ.get("CONTRACTS_EXTRACT_SINCE") or ""
ANNOUNCEMENTS_PER_CALL = 12        # big end-of-fiscal-year bulletins are split into several calls
MAX_RUNTIME_MINUTES = float(os.environ.get("MAX_RUNTIME_MINUTES") or "320")
# Bump when parse.py or extract.py change in a way that should reprocess stored bulletins.
PROCESSING_VERSION = 1
