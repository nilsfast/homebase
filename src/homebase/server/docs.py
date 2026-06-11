from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from homebase.core.config import db, templates
from homebase.server.helpers import (
    _all_entities_options,
    _base_context,
    _require_doc,
    _require_entity,
    _resolve_link,
)


router = APIRouter()


def _render_items(request: Request, doc: dict, new_item: bool = False) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "docs/content_steps.html",
        {"doc": doc, "new_item": new_item, **_base_context()},
    )


# --- Entity Docs Page ---


@router.get("/inventory/{entity_type}/{doc_id}/docs", response_class=HTMLResponse)
def html_entity_docs(request: Request, entity_type: str, doc_id: int):
    entity = _require_entity(entity_type)
    item = _require_doc(entity_type, doc_id)

    docs = db.get_all_docs()

    entity_relevant_docs = []
    for doc in docs:
        if f"homebase://{entity_type}/{doc_id}" in doc.get("related_entities", []):
            entity_relevant_docs.append(doc)

    return templates.TemplateResponse(
        request,
        "entity_docs.html",
        {
            **_base_context(entity_type),
            "entity": entity,
            "item": item,
            "docs": entity_relevant_docs,
            "active_tab": "docs",
        },
    )


# --- Document Pages ---


@router.get("/document/", response_class=HTMLResponse)
async def html_get_docs(request: Request):
    docs = db.get_all_docs()
    return templates.TemplateResponse(
        request,
        "docs_list.html",
        {
            **_base_context(),
            "docs": docs,
        },
    )


@router.get("/document/new")
def new_doc_form(request: Request):

    return templates.TemplateResponse(
        request,
        "docs/doc_form.html",
        {
            **_base_context(),
            "related_options": _all_entities_options(),
            "doc": None,
        },
    )


@router.get("/document/{id}", response_class=HTMLResponse)
def html_doc(request: Request, id: int):
    doc = db.get_doc(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return templates.TemplateResponse(
        request,
        "docs/doc_page.html",
        {
            "resolve_link": _resolve_link,
            **_base_context(),
            "doc": doc,
        },
    )


@router.get("/document/{id}/edit")
def edit_doc_form(request: Request, id: int):
    doc = db.get_doc(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    related_options = _all_entities_options()
    print(f"Related options for document edit form: {related_options}")

    return templates.TemplateResponse(
        request,
        "docs/doc_form.html",
        {
            **_base_context(),
            "related_options": related_options,
            "doc": doc,
        },
    )


# --- Document API Endpoints ---


@router.post("/api/document")
async def api_create_doc(
    title: str = Form(...),
    description: str = Form(""),
    related_entities: str = Form(""),
):
    doc = {
        "title": title,
        "description": description,
        "content": [],
        "related_entities": related_entities.split(",")
        if isinstance(related_entities, str)
        else related_entities,
    }

    created_id = db.create_doc(doc)
    return {"id": created_id}


@router.post("/api/document/{id}")
async def api_edit_doc(
    id: int,
    title: str = Form(...),
    description: str = Form(...),
    related_entities: str = Form(...),
):
    doc = db.get_doc(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc["title"] = title
    doc["description"] = description
    doc["related_entities"] = (
        related_entities.split(",")
        if isinstance(related_entities, str)
        else related_entities
    )
    db.update_doc(id, doc)

    return {"success": True}


@router.delete("/api/document/{id}")
async def api_delete_doc(id: int):
    doc = db.get_doc(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    db.delete_doc(id)
    return {"success": True}


# --- Document content items ---


@router.post("/document/{id}/items")
async def html_document_add_item(request: Request, id: int):
    doc = db.get_doc(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc["content"].append({"type": "text", "text": ""})
    db.update_doc(id, doc)

    return _render_items(request, doc, new_item=True)


@router.patch("/document/{id}/items")
async def html_document_reorder_items(
    request: Request, id: int, order: list[int] = Form(...)
):
    doc = db.get_doc(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc["content"] = [doc["content"][i - 1] for i in order]
    db.update_doc(id, doc)

    return _render_items(request, doc)


@router.patch("/document/{id}/items/{n}")
async def html_document_update_item(
    request: Request, id: int, n: int, content: str = Form(...)
):
    doc = db.get_doc(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if n < 1 or n > len(doc["content"]):
        raise HTTPException(status_code=404, detail="Item not found")

    step = doc["content"][n - 1]
    if step["type"] == "text":
        step["text"] = content
    else:
        step["content"] = content
    db.update_doc(id, doc)

    return _render_items(request, doc)


@router.delete("/document/{id}/items/{n}")
async def html_document_delete_item(request: Request, id: int, n: int):
    doc = db.get_doc(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if n < 1 or n > len(doc["content"]):
        raise HTTPException(status_code=404, detail="Item not found")

    doc["content"].pop(n - 1)
    db.update_doc(id, doc)

    return _render_items(request, doc)
