from pathlib import Path
from typing import Callable, Iterable

from tinydb import TinyDB
from tinydb.table import Document


def _with_id(doc: Document) -> dict:
    return dict(doc) | {"id": doc.doc_id}


BUILTIN_TABLES = [("docs", "_documents")]


class TableService:
    def __init__(self, db: TinyDB, entity_type: str):
        self._db = db
        self._entity_type = entity_type

    def all(self) -> list[dict]:
        return [_with_id(d) for d in self._db.table(self._entity_type).all()]

    def get(self, doc_id: int) -> dict | None:
        doc = self._db.table(self._entity_type).get(doc_id=doc_id)
        if doc is None or isinstance(doc, list):
            return None
        return _with_id(doc)

    def search(self, predicate: Callable) -> list[dict]:
        return [
            _with_id(d) for d in self._db.table(self._entity_type).search(predicate)
        ]

    def create(self, doc: dict) -> int:
        return self._db.table(self._entity_type).insert(doc)

    def update(self, doc_id: int, doc: dict) -> None:
        self._db.table(self._entity_type).update(doc, doc_ids=[doc_id])

    def delete(self, doc_id: int) -> None:
        self._db.table(self._entity_type).remove(doc_ids=[doc_id])


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(exist_ok=True)
        self._db = TinyDB(path)

    def table(self, entity_type: str) -> TableService:
        return TableService(self._db, entity_type)

    def has_table(self, entity_type: str) -> bool:
        return entity_type in self._db.tables()

    # BUILTIN_TABLES via Database.table.
    def __getattr__(self, name: str) -> TableService:
        if name in [t[0] for t in BUILTIN_TABLES]:
            return self.table(dict(BUILTIN_TABLES)[name])
        raise AttributeError(f"Database has no table '{name}'")

    def counts(self, entity_names: Iterable[str]) -> dict[str, int]:
        return {name: len(self._db.table(name).all()) for name in entity_names}
