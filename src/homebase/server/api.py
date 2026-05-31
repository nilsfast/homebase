from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from homebase.server.helpers import (
    _base_context,
)
from homebase.server.inventory import api_list_entities
from homebase.core.config import schema


app = FastAPI(title="homebase", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
app.mount(
    "/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static"
)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@app.get("/api/schema")
def get_schema():
    return schema.to_dict()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    first = next(iter(schema.entities))
    return RedirectResponse(f"inventory/{first}", status_code=302)


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


if __name__ == "__main__":
    import uvicorn
    from homebase.core.config import HOST, PORT

    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
