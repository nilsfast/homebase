from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from homebase.core.config import db, templates
from fastapi import Form
from homebase.server.helpers import (
    _base_context,
    _require_doc,
    _require_entity,
    _resolve_link,
)


router = APIRouter()


@router.get("/inventory/{entity_type}/{doc_id}/docs", response_class=HTMLResponse)
def html_entity_docs(request: Request, entity_type: str, doc_id: int):
    entity = _require_entity(entity_type)
    item = _require_doc(entity_type, doc_id)

    docs = db.get_all_docs()

    return templates.TemplateResponse(
        request,
        "entity_docs.html",
        {
            **_base_context(entity_type),
            "entity": entity,
            "item": item,
            "docs": docs,
            "active_tab": "docs",
        },
    )


@router.get("/docs/{id}", response_class=HTMLResponse)
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


@router.post("/document")
async def api_create_doc(title: str = Form(...)):
    doc = {
        "title": title,
        "content": [],
    }
    created_id = db.create_doc(doc)
    return {"id": created_id}


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


@router.get("/document/{id}/add-content")
def api_add_doc_content_form(request: Request, id: int, after: int = 0):
    doc = db.get_doc(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return templates.TemplateResponse(
        request,
        "docs/add_doc_content.html",
        {
            **_base_context(),
            "doc": doc,
            "after": after,
        },
    )


@router.post("/document/{id}/add-content")
async def api_add_doc_content(id: int, content: str = Form(...), after: int = Form(0)):
    doc = db.get_doc(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    new_content = {"type": "text", "text": content}

    if not after:
        # If no "after" specified, append to the beginning
        doc["content"].insert(0, new_content)

    else:
        # insert at the given position
        doc["content"].insert(after, new_content)

    db.update_doc(id, doc)

    # now return the document html to replace the whole page
    return templates.TemplateResponse(
        Request(scope={"type": "http"}),  # dummy request for rendering
        "docs/doc_page.html",
        {
            "resolve_link": _resolve_link,
            **_base_context(),
            "doc": doc,
        },
    )
