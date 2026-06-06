from pathlib import Path
from typing import Callable, Iterable

from tinydb import TinyDB
from tinydb.table import Document


def _with_id(doc: Document) -> dict:
    return dict(doc) | {"id": doc.doc_id}


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(exist_ok=True)
        self._db = TinyDB(path)

    def counts(self, entity_names: Iterable[str]) -> dict[str, int]:
        return {name: len(self._db.table(name).all()) for name in entity_names}

    def all(self, entity_type: str) -> list[dict]:
        return [_with_id(d) for d in self._db.table(entity_type).all()]

    def get(self, entity_type: str, doc_id: int) -> dict | None:
        doc = self._db.table(entity_type).get(doc_id=doc_id)
        if doc is None or isinstance(doc, list):
            return None
        return _with_id(doc)

    def search(self, entity_type: str, predicate: Callable) -> list[dict]:
        return [_with_id(d) for d in self._db.table(entity_type).search(predicate)]

    def create(self, entity_type: str, doc: dict) -> int:
        return self._db.table(entity_type).insert(doc)

    def update(self, entity_type: str, doc_id: int, doc: dict) -> None:
        self._db.table(entity_type).update(doc, doc_ids=[doc_id])

    def delete(self, entity_type: str, doc_id: int) -> None:
        self._db.table(entity_type).remove(doc_ids=[doc_id])

    # DOCUMENTS (extra Table documents)

    def get_doc(self, doc_id: int) -> dict | None:
        doc = self._db.table("_documents").get(doc_id=doc_id)
        if doc is None or isinstance(doc, list):
            return None
        return _with_id(doc)

    def get_all_docs(self) -> list[dict]:
        return [_with_id(d) for d in self._db.table("_documents").all()]

    def create_doc(self, doc: dict) -> int:
        return self._db.table("_documents").insert(doc)

    def search_docs(self, predicate: Callable) -> list[dict]:
        return [_with_id(d) for d in self._db.table("_documents").search(predicate)]

    def update_doc(self, doc_id: int, doc: dict) -> None:
        self._db.table("_documents").update(doc, doc_ids=[doc_id])

    def delete_doc(self, doc_id: int) -> None:
        self._db.table("_documents").remove(doc_ids=[doc_id])
