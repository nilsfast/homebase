import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from tinydb import TinyDB
from tinydb.table import Document

from app.backend.schema import Schema, ValidationError

# Configuration

SCHEMA_PATH = Path("schema.yaml")
DB_PATH = Path("data/db.json")

# Bootstrap

DB_PATH.parent.mkdir(exist_ok=True)


schema = Schema.from_file(SCHEMA_PATH)
db = TinyDB(DB_PATH)

app = FastAPI(title="homebase", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


templates = Jinja2Templates(directory="app/templates")

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


def _counts() -> dict[str, int]:
    return {name: len(db.table(name).all()) for name in schema.entities}


def _resolve_relation(target_entity: str, doc_id) -> str:
    """Resolve a relation ID to its display name."""
    try:
        doc_id = int(doc_id)
    except TypeError, ValueError:
        return str(doc_id)
    table = db.table(target_entity)
    doc = table.get(doc_id=doc_id)
    if not doc:
        return f"#{doc_id}"
    edef = schema.get_entity(target_entity)
    return doc.get(edef.display_field, f"#{doc_id}")


def _relation_options(entity_type: str) -> dict[str, list[dict]]:
    """Get all possible relation targets for an entity's relation fields."""
    entity = schema.get_entity(entity_type)
    opts: dict[str, list[dict]] = {}
    for f in entity.relation_fields:
        if f.target not in opts:
            target_edef = schema.get_entity(f.target)
            table = db.table(f.target)
            opts[f.target] = [
                {
                    "id": r.doc_id,
                    "display": r.get(target_edef.display_field, f"#{r.doc_id}"),
                }
                for r in table.all()
            ]
    return opts


def _base_context(active_entity: str | None = None) -> dict:

    return {
        "entities": schema.entities,
        "counts": _counts(),
        "active_entity": active_entity,
        "schema_entities": schema.entities,
        "sidebar_entities": {
            name: edef for name, edef in schema.entities.items() if not edef.junction
        },
        "resolve_relation": _resolve_relation,
    }


def _fields_json(entity_type: str) -> str:
    """Serialize entity fields to a JSON string safe for embedding in JS."""
    import json

    entity = schema.get_entity(entity_type)
    out = {}
    for fname, fdef in entity.fields.items():
        out[fname] = fdef.to_dict()
    return json.dumps(out)


# Routes


@app.get("/api/schema")
def get_schema():
    return schema.to_dict()


@app.get("/api/{entity_type}")
def api_list_entities(
    entity_type: str,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
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
def api_get_entity(entity_type: str, doc_id: int):
    table = _table(entity_type)
    doc = table.get(doc_id=doc_id)
    doc = _validate_doc(doc)
    out = dict(doc) | {"id": doc.doc_id}
    return out


@app.post("/api/{entity_type}", status_code=201)
def api_create_entity(entity_type: str, body: dict):
    try:
        cleaned = schema.validate(entity_type, body)
    except ValidationError as e:
        raise HTTPException(422, detail=e.errors)

    cleaned["_created"] = cleaned["_updated"] = time.time()
    doc_id = _table(entity_type).insert(cleaned)
    return {"id": doc_id}


@app.put("/api/{entity_type}/{doc_id}")
def api_update_entity(entity_type: str, doc_id: int, body: dict):
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
def api_delete_entity(entity_type: str, doc_id: int):
    table = _table(entity_type)
    if not table.get(doc_id=doc_id):
        raise HTTPException(404, "Not found")
    table.remove(doc_ids=[doc_id])
    return {"deleted": doc_id}


@app.get("/api/{entity_type}/{doc_id}/related/{target_type}")
def api_get_related(entity_type: str, doc_id: int, target_type: str):
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


# HTML Routes (HTMX frontend)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # Redirect to first entity type.
    first = next(iter(schema.entities))
    return RedirectResponse(f"/{first}", status_code=302)


@app.get("/search", response_class=HTMLResponse)
def html_search(request: Request, q: str):
    # Search across all entities and render a combined results page.
    results = []
    print("Search query:", q)
    for entity_type in schema.entities:
        data = api_list_entities(entity_type, q=q, limit=5)
        if data["items"]:
            results.append(
                (schema.get_entity(entity_type), data["items"], data["total"])
            )

    print("Search results:", results)

    return templates.TemplateResponse(
        request,
        "search_results.html",
        {
            **_base_context(),
            "query": q,
            "results": results,
        },
    )


@app.get("/{entity_type}", response_class=HTMLResponse)
def html_list(request: Request, entity_type: str, q: str | None = None):
    _table(entity_type)  # validate
    entity = schema.get_entity(entity_type)
    data = api_list_entities(entity_type, q=q)

    # TODO overthink
    if entity.junction:
        return HTMLResponse(
            f"<html><body><h1>{entity.name} is a junction entity and cannot be listed directly.</h1></body></html>"
        )

    return templates.TemplateResponse(
        request,
        "entity_list.html",
        {
            **_base_context(entity_type),
            "entity": entity,
            "items": data["items"],
            "total": data["total"],
            "q": q,
        },
    )


@app.get("/{entity_type}/new", response_class=HTMLResponse)
def html_new(request: Request, entity_type: str):
    entity = schema.get_entity(entity_type)

    # Pre-fill form with query parameters
    prefill = {}
    for field_name in entity.fields:
        if field_name in request.query_params:
            prefill[field_name] = request.query_params[field_name]

    print("Prefill data:", prefill)

    return templates.TemplateResponse(
        request,
        "entity_form.html",
        {
            **_base_context(entity_type),
            "entity": entity,
            "item": prefill if prefill else None,
            "edit_mode": False,
            "relation_options": _relation_options(entity_type),
            "fields_json": _fields_json(entity_type),
        },
    )


@app.get("/{entity_type}/{doc_id}", response_class=HTMLResponse)
def html_detail(request: Request, entity_type: str, doc_id: int):
    entity = schema.get_entity(entity_type)
    table = _table(entity_type)
    doc = table.get(doc_id=doc_id)
    doc = _validate_doc(doc)
    item = doc | {"id": doc.doc_id}

    # Gather reverse-related items.
    reverse_rels = schema.get_reverse_relations_for(entity_type)
    related_items: dict[str, list] = {}
    for rel in reverse_rels:
        rel_table = db.table(rel["entity"])
        field_name = rel["field"]
        results = rel_table.search(
            lambda d, fn=field_name, did=doc_id: (
                d.get(fn) == did or (isinstance(d.get(fn), list) and did in d.get(fn))
            )
        )

        related_items[rel["entity"]] = [(dict(r) | {"id": r.doc_id}) for r in results]

    print("Related items:", related_items)

    return templates.TemplateResponse(
        request,
        "entity_detail.html",
        {
            **_base_context(entity_type),
            "entity": entity,
            "item": item,
            "reverse_relations": reverse_rels,
            "related_items": related_items,
        },
    )


@app.get("/{entity_type}/{doc_id}/edit", response_class=HTMLResponse)
def html_edit(request: Request, entity_type: str, doc_id: int):
    entity = schema.get_entity(entity_type)
    table = _table(entity_type)
    doc = table.get(doc_id=doc_id)
    doc = _validate_doc(doc)
    item = dict(doc) | {"id": doc.doc_id}

    return templates.TemplateResponse(
        request,
        "entity_form.html",
        {
            **_base_context(entity_type),
            "entity": entity,
            "item": item,
            "edit_mode": True,
            "relation_options": _relation_options(entity_type),
            "fields_json": _fields_json(entity_type),
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
