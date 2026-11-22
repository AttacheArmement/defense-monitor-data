"""FMS-specific settings."""
import os

# One JSON file per notice lives here (committed to the repo): data/fms/notices/<year>/<document_number>.json
NOTICES_DIR = os.environ.get("FMS_NOTICES_DIR") or "data/fms/notices"
# SQLite database built from the JSON files for querying (not committed; rebuilt in seconds).
DB_PATH = os.environ.get("FMS_DB_PATH") or "data/fms.db"

SEARCH_TERM = os.environ.get("FR_SEARCH_TERM") or '"Arms Sales Notification"'
# Keep only documents whose title contains this text (case-insensitive). Set to "-" to keep everything.
TITLE_FILTER = os.environ.get("FR_TITLE_FILTER") or "arms sales"
if TITLE_FILTER == "-":
    TITLE_FILTER = ""
DEFAULT_LOOKBACK_DAYS = int(os.environ.get("DEFAULT_LOOKBACK_DAYS") or "30")
OVERLAP_DAYS = 3  # re-check the last few days each run; duplicates are skipped by document number
MAX_NOTICE_CHARS = 80_000
# Stop processing new notices after this many minutes so the job can save its progress before
# GitHub's 6-hour limit. Anything not processed is picked up by the next run.
MAX_RUNTIME_MINUTES = float(os.environ.get("MAX_RUNTIME_MINUTES") or "320")
