import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.backend.db import Database
from app.backend.schema import EntityDef, Schema, ValidationError

# Configuration

SCHEMA_PATH = Path("schema.yaml")
DB_PATH = Path("data/db.json")

# Bootstrap

schema = Schema.from_file(SCHEMA_PATH)
db = Database(DB_PATH)

app = FastAPI(title="homebase", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

# Helpers


def _require_entity(entity_type: str) -> EntityDef:
    if entity_type not in schema.entities:
        raise HTTPException(404, f"Unknown entity: {entity_type}")
    return schema.get_entity(entity_type)


def _require_doc(entity_type: str, doc_id: int) -> dict:
    doc = db.get(entity_type, doc_id)
    if doc is None:
        raise HTTPException(404, "Not found")
    return doc


def _resolve_relation(target_entity: str, doc_id) -> str:
    try:
        doc_id = int(doc_id)
    except TypeError, ValueError:
        return str(doc_id)
    doc = db.get(target_entity, doc_id)
    if doc is None:
        return f"#{doc_id}"
    edef = schema.get_entity(target_entity)
    return doc.get(edef.display_field, f"#{doc_id}")


def _relation_options(entity_type: str) -> dict[str, list[dict]]:
    entity = schema.get_entity(entity_type)
    opts: dict[str, list[dict]] = {}
    for f in entity.relation_fields:
        assert f.target is not None
        if f.target not in opts:
            target_edef = schema.get_entity(f.target)
            opts[f.target] = [
                {
                    "id": r["id"],
                    "display": r.get(target_edef.display_field, f"#{r['id']}"),
                }
                for r in db.all(f.target)
            ]
    return opts


def _base_context(active_entity: str | None = None) -> dict:
    return {
        "entities": schema.entities,
        "counts": db.counts(schema.entities),
        "active_entity": active_entity,
        "schema_entities": schema.entities,
        "sidebar_entities": {
            name: edef for name, edef in schema.entities.items() if not edef.junction
        },
        "resolve_relation": _resolve_relation,
    }


def _fields_json(entity_type: str) -> str:
    entity = schema.get_entity(entity_type)
    return json.dumps({fname: fdef.to_dict() for fname, fdef in entity.fields.items()})


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
    entity = _require_entity(entity_type)

    if q:
        q_lower = q.lower()
        searchable = entity.searchable_fields
        results = db.search(
            entity_type,
            lambda doc: any(
                q_lower in str(doc.get(f.name, "")).lower() for f in searchable
            ),
        )
    else:
        results = db.all(entity_type)

    return {"items": results[offset : offset + limit], "total": len(results)}


@app.get("/api/{entity_type}/{doc_id}")
def api_get_entity(entity_type: str, doc_id: int):
    _require_entity(entity_type)
    return _require_doc(entity_type, doc_id)


@app.post("/api/{entity_type}", status_code=201)
def api_create_entity(entity_type: str, body: dict):
    _require_entity(entity_type)
    try:
        cleaned = schema.validate(entity_type, body)
    except ValidationError as e:
        raise HTTPException(422, detail=e.errors)

    cleaned["_created"] = cleaned["_updated"] = time.time()
    doc_id = db.create(entity_type, cleaned)
    return {"id": doc_id}


@app.put("/api/{entity_type}/{doc_id}")
def api_update_entity(entity_type: str, doc_id: int, body: dict):
    _require_entity(entity_type)
    _require_doc(entity_type, doc_id)
    try:
        cleaned = schema.validate(entity_type, body, partial=True)
    except ValidationError as e:
        raise HTTPException(422, detail=e.errors)

    cleaned["_updated"] = time.time()
    db.update(entity_type, doc_id, cleaned)
    return {"id": doc_id}


@app.delete("/api/{entity_type}/{doc_id}")
def api_delete_entity(entity_type: str, doc_id: int):
    _require_entity(entity_type)
    _require_doc(entity_type, doc_id)
    db.delete(entity_type, doc_id)
    return {"deleted": doc_id}


@app.get("/api/{entity_type}/{doc_id}/related/{target_type}")
def api_get_related(entity_type: str, doc_id: int, target_type: str):
    entity_def = _require_entity(entity_type)
    _require_entity(target_type)
    source_doc = _require_doc(entity_type, doc_id)

    # Forward: this entity has a relation field pointing to target_type.
    for f in entity_def.relation_fields:
        if f.target == target_type:
            ref = source_doc.get(f.name)
            if ref is None:
                return {"items": []}
            ids = ref if isinstance(ref, list) else [ref]
            items = [doc for i in ids if (doc := db.get(target_type, i)) is not None]
            return {"items": items}

    # Reverse: target_type has a relation field pointing to entity_type.
    for rev in schema.get_reverse_relations_for(entity_type):
        if rev["entity"] == target_type:
            field_name = rev["field"]
            results = db.search(
                target_type,
                lambda doc, fn=field_name, did=doc_id: (
                    doc.get(fn) == did
                    or (isinstance(doc.get(fn), list) and did in doc.get(fn))  # type: ignore
                ),
            )
            return {"items": results}

    raise HTTPException(400, f"No relation between {entity_type} and {target_type}")


# HTML Routes (HTMX frontend)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    first = next(iter(schema.entities))
    return RedirectResponse(f"/{first}", status_code=302)


@app.get("/search", response_class=HTMLResponse)
def html_search(request: Request, q: str):
    results = []
    for entity_type in schema.entities:
        data = api_list_entities(entity_type, q=q, limit=5)
        if data["items"]:
            results.append(
                (schema.get_entity(entity_type), data["items"], data["total"])
            )

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
    entity = _require_entity(entity_type)
    data = api_list_entities(entity_type, q=q)

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
    entity = _require_entity(entity_type)

    prefill = {}
    for field_name in entity.fields:
        if field_name in request.query_params:
            prefill[field_name] = request.query_params[field_name]

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
    entity = _require_entity(entity_type)
    item = _require_doc(entity_type, doc_id)

    reverse_rels = schema.get_reverse_relations_for(entity_type)
    related_items: dict[str, list] = {}
    for rel in reverse_rels:
        field_name = rel["field"]
        results = db.search(
            rel["entity"],
            lambda d, fn=field_name, did=doc_id: (
                d.get(fn) == did or (isinstance(d.get(fn), list) and did in d.get(fn))
            ),
        )
        related_items[rel["entity"]] = results

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
    entity = _require_entity(entity_type)
    item = _require_doc(entity_type, doc_id)

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
