import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from homebase.core.config import db, schema, templates
from homebase.core.schema import ValidationError
from homebase.server.helpers import (
    _base_context,
    _fields_json,
    _relation_options,
    _require_doc,
    _require_entity,
)


router = APIRouter()


FIELD_DETAIL_WIDTHS = {
    "string": 40,
    "number": 30,
    "boolean": 20,
    "date": 30,
    "datetime": 40,
    "url": 40,
    "email": 40,
    "enum": 30,
    "tags": 40,
    "markdown": 100,
    "relation": 100,
    "json": 100,
    "list": 100,
}


@router.get("/search", response_class=HTMLResponse)
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


@router.get("/api/inventory/{entity_type}")
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


@router.get("/api/inventory/{entity_type}/{doc_id}")
def api_get_entity(entity_type: str, doc_id: int):
    _require_entity(entity_type)
    return _require_doc(entity_type, doc_id)


@router.post("/api/inventory/{entity_type}", status_code=201)
def api_create_entity(entity_type: str, body: dict):
    _require_entity(entity_type)
    try:
        cleaned = schema.validate(entity_type, body)
    except ValidationError as e:
        raise HTTPException(422, detail=e.errors)

    cleaned["_created"] = cleaned["_updated"] = time.time()
    doc_id = db.create(entity_type, cleaned)
    return {"id": doc_id}


@router.put("/api/inventory/{entity_type}/{doc_id}")
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


@router.delete("/api/inventory/{entity_type}/{doc_id}")
def api_delete_entity(entity_type: str, doc_id: int):
    _require_entity(entity_type)
    _require_doc(entity_type, doc_id)
    db.delete(entity_type, doc_id)
    return {"deleted": doc_id}


@router.get("/api/inventory/{entity_type}/{doc_id}/related/{target_type}")
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


@router.get("/inventory/{entity_type}", response_class=HTMLResponse)
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


@router.get("/inventory/{entity_type}/new", response_class=HTMLResponse)
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


@router.get("/inventory/{entity_type}/{doc_id}", response_class=HTMLResponse)
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
            "field_width": FIELD_DETAIL_WIDTHS,
            "item": item,
            "reverse_relations": reverse_rels,
            "related_items": related_items,
        },
    )


@router.get("/inventory/{entity_type}/{doc_id}/edit", response_class=HTMLResponse)
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
