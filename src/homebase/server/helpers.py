import json
from fastapi import HTTPException, Request
from homebase.core.schema import EntityDef
from homebase.core.config import schema, db


def _require_entity(entity_type: str) -> EntityDef:
    if entity_type not in schema.entities:
        raise HTTPException(404, f"Unknown entity: {entity_type}")
    return schema.get_entity(entity_type)


def _require_doc(entity_type: str, doc_id: int) -> dict:
    doc = db.get(entity_type, doc_id)
    if doc is None:
        raise HTTPException(404, "Not found")
    return doc


def _resolve_relation(
    target_entity: str, doc_id_or_link
) -> tuple[str, str, int] | tuple[str, None]:
    # returns the display value and its link (entity_type, id) if applicable
    if target_entity == "*":
        # wildcard relation: doc_id is expected to be in the format "homebase://entity_type/id"
        if not isinstance(doc_id_or_link, str) or not doc_id_or_link.startswith(
            "homebase://"
        ):
            print(f"Invalid wildcard relation link: '{doc_id_or_link}'")
            return str(doc_id_or_link), None
        try:
            doc_id_or_link = doc_id_or_link[len("homebase://") :]
            entity_type, id_str = doc_id_or_link.split("/", 2)
            doc_id = int(id_str)
        except ValueError:
            print(f"Invalid wildcard relation link format: '{doc_id_or_link}'")
            return str(doc_id_or_link), None
        target_entity = entity_type
        print(
            f"Resolving wildcard relation link '{doc_id_or_link}' to entity '{target_entity}' and id {doc_id}"
        )
    else:
        try:
            doc_id = int(doc_id_or_link)
        except TypeError, ValueError:
            print(
                f"Invalid relation doc_id: '{doc_id_or_link}' for target entity '{target_entity}'"
            )
            return str(doc_id_or_link), None
    doc = db.get(target_entity, doc_id)
    if doc is None:
        print(
            f"Related document not found for entity '{target_entity}' and id {doc_id}"
        )
        return f"#{doc_id}", None
    edef = schema.get_entity(target_entity)
    return doc.get(edef.display_field, f"#{doc_id}"), target_entity, doc_id


def _resolve_link(link: str):
    return _resolve_relation("*", link)


def _relation_options(entity_type: str) -> dict[str, list[dict]]:
    entity = schema.get_entity(entity_type)
    opts: dict[str, list[dict]] = {}
    for f in entity.relation_fields:
        assert f.target is not None
        if f.target == "*":
            all_opts = []
            for entity_slug, entity in schema.entities.items():
                target_edef = schema.get_entity(entity_slug)
                all_opts.extend(
                    {
                        "id": f"homebase://{entity_slug}/{r['id']}",
                        "display": f"{entity.label}: {r.get(target_edef.display_field, f'#{r["id"]}')}",
                    }
                    for r in db.all(entity_slug)
                )
            opts["*"] = all_opts
            print(f"Wildcard relation field '{f.name}' options: {opts['*']}")
        elif f.target not in opts:
            target_edef = schema.get_entity(f.target)
            opts[f.target] = [
                {
                    "id": r["id"],
                    "display": r.get(target_edef.display_field, f"#{r['id']}"),
                }
                for r in db.all(f.target)
            ]
    return opts


# All entities
def _all_entities_options() -> list[dict]:
    opts = []
    for entity_slug in schema.entities:
        for doc in db.all(entity_slug):
            edef = schema.get_entity(entity_slug)
            opts.append(
                {
                    "id": f"homebase://{entity_slug}/{doc['id']}",
                    "display": f"{edef.label}: {doc.get(edef.display_field, f'#{doc["id"]}')}",
                }
            )
    return opts


def _base_context(
    active_entity: str | None = None, request: Request | None = None
) -> dict:
    is_htmx = request is not None and request.headers.get("HX-Request") == "true"
    return {
        "entities": schema.entities,
        "counts": db.counts(schema.entities),
        "active_entity": active_entity,
        "schema_entities": schema.entities,
        "sidebar_entities": {
            name: edef for name, edef in schema.entities.items() if not edef.junction
        },
        "resolve_relation": _resolve_relation,
        "base_template": "_shell.html" if is_htmx else "base.html",
    }


def _fields_json(entity_type: str) -> str:
    entity = schema.get_entity(entity_type)
    return json.dumps({fname: fdef.to_dict() for fname, fdef in entity.fields.items()})
