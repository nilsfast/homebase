import os
from pathlib import Path

from homebase.core.db import Database
from homebase.core.schema import Schema

SCHEMA_PATH = Path(os.environ.get("HOMEBASE_SCHEMA_PATH", "schema.yaml"))
DB_PATH = Path(os.environ.get("HOMEBASE_DB_PATH", "data/db.json"))
HOST = os.environ.get("HOMEBASE_HOST", "0.0.0.0")
PORT = int(os.environ.get("HOMEBASE_PORT", "8000"))


schema = Schema.from_file(SCHEMA_PATH)
db = Database(DB_PATH)
