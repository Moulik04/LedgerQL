"""Stage 8: audit trail.

Appends one JSON record per request to logs/audit.jsonl -- the source
of truth for the master prompt's hard constraint #4 (every query is
logged; nothing is silently dropped). No live table, no migrations:
DuckDB reads JSONL directly (read_json_auto) whenever a later phase
needs to query it, so a live table would be duplicated state for no
present benefit.
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "audit.jsonl"


def write_record(record: dict, log_path: Path = LOG_PATH) -> str:
    record_id = str(uuid.uuid4())
    full_record = {
        "id": record_id,
        "timestamp": datetime.now(UTC).isoformat(),
        **record,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(full_record) + "\n")
    return record_id
