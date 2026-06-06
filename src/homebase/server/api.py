from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from homebase.core.config import schema

from homebase.server.inventory import router as inventory_router
from homebase.server.docs import router as document_router


app = FastAPI(title="homebase", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
app.mount(
    "/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static"
)
app.include_router(inventory_router)
app.include_router(document_router)


@app.get("/api/schema")
def get_schema():
    return schema.to_dict()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    first = next(iter(schema.entities))
    return RedirectResponse(f"inventory/{first}", status_code=302)
