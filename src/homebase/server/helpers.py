import json

from fastapi import HTTPException
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
