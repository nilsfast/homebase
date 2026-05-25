from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from tinydb import TinyDB
from tinydb.table import Document

from app.backend.schema import Schema, ValidationError

# Configuration

SCHEMA_PATH = Path("schema.yaml")
DB_PATH = Path("data/db.json")
SECRET_KEY = Path(".secret_key")

# Bootstrap

DB_PATH.parent.mkdir(exist_ok=True)


schema = Schema.from_file(SCHEMA_PATH)
db = TinyDB(DB_PATH)

app = FastAPI(title="homelab-docs", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# Helpers


def _table(entity_type: str):
    if entity_type not in schema.entities:
        raise HTTPException(404, f"Unknown entity: {entity_type}")
    return db.table(entity_type)


def _validate_doc(doc) -> Document:
    if not doc:
        raise HTTPException(404, "Not found")
    # check if the document is not a list, if it is, return an error
    if isinstance(doc, list):
        raise HTTPException(500, "Document is a list, expected a dict")
    return doc


# Routes


@app.get("/api/schema")
def get_schema():
    return schema.to_dict()


@app.get("/api/{entity_type}")
def list_entities(
    entity_type: str,
    q: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    table = _table(entity_type)

    if q:
        q_lower = q.lower()
        searchable = schema.get_entity(entity_type).searchable_fields
        results = table.search(
            lambda doc: any(
                q_lower in str(doc.get(f.name, "")).lower() for f in searchable
            )
        )
    else:
        results = table.all()

    items = [dict(d) | {"id": d.doc_id} for d in results[offset : offset + limit]]
    return {"items": items, "total": len(results)}


@app.get("/api/{entity_type}/{doc_id}")
def get_entity(entity_type: str, doc_id: int):
    table = _table(entity_type)
    doc = table.get(doc_id=doc_id)
    doc = _validate_doc(doc)
    out = dict(doc) | {"id": doc.doc_id}
    return out


@app.post("/api/{entity_type}", status_code=201)
def create_entity(entity_type: str, body: dict):
    try:
        cleaned = schema.validate(entity_type, body)
    except ValidationError as e:
        raise HTTPException(422, detail=e.errors)

    cleaned["_created"] = cleaned["_updated"] = time.time()
    doc_id = _table(entity_type).insert(cleaned)
    return {"id": doc_id}


@app.put("/api/{entity_type}/{doc_id}")
def update_entity(entity_type: str, doc_id: int, body: dict):
    table = _table(entity_type)
    if not table.get(doc_id=doc_id):
        raise HTTPException(404, "Not found")

    try:
        cleaned = schema.validate(entity_type, body, partial=True)
    except ValidationError as e:
        raise HTTPException(422, detail=e.errors)

    cleaned["_updated"] = time.time()
    table.update(cleaned, doc_ids=[doc_id])
    return {"id": doc_id}


@app.delete("/api/{entity_type}/{doc_id}")
def delete_entity(entity_type: str, doc_id: int):
    table = _table(entity_type)
    if not table.get(doc_id=doc_id):
        raise HTTPException(404, "Not found")
    table.remove(doc_ids=[doc_id])
    return {"deleted": doc_id}


@app.get("/api/{entity_type}/{doc_id}/related/{target_type}")
def get_related(entity_type: str, doc_id: int, target_type: str):
    """Get entities of target_type that reference this doc, or that this doc references."""
    _table(entity_type)  # validate source exists
    target_table = _table(target_type)

    # Forward: this entity has a relation field pointing to target_type.
    entity_def = schema.get_entity(entity_type)
    source_doc = _table(entity_type).get(doc_id=doc_id)
    source_doc = _validate_doc(source_doc)

    for f in entity_def.relation_fields:
        if f.target == target_type:
            ref = source_doc.get(f.name)
            if ref is None:
                return {"items": []}
            ids = ref if isinstance(ref, list) else [ref]
            items = [
                dict(d) | {"id": d.doc_id}
                for d in _validate_doc(target_table.get(doc_id=i) for i in ids)
                if d
            ]
            return {"items": items}

    # Reverse: target_type has a relation field pointing to entity_type.
    for rev in schema.get_reverse_relations_for(entity_type):
        if rev["entity"] == target_type:
            field_name = rev["field"]
            results = target_table.search(
                lambda doc, fn=field_name, did=doc_id: (
                    doc.get(fn) == did
                    or (isinstance(doc.get(fn), list) and did in doc.get(fn))  # type: ignore
                )
            )

            return {"items": results}

    raise HTTPException(400, f"No relation between {entity_type} and {target_type}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
