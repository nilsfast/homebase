import json
import re
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

# CONSTANTS

MAX_COLORS = 12  # for auto-assigning entity colors

# ──────────────────────────────────────────────
# Field type registry
# ──────────────────────────────────────────────


class FieldType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    URL = "url"
    EMAIL = "email"
    ENUM = "enum"
    TAGS = "tags"
    MARKDOWN = "markdown"
    RELATION = "relation"
    JSON = "json"  # arbitrary nested data
    LIST = "list"  # list of primitives


# Per-type validators.  Each returns (ok: bool, cleaned_value | error_msg).
def _validate_string(value: Any, field_def: dict) -> tuple[bool, Any]:
    if not isinstance(value, str):
        return False, "expected string"
    mx = field_def.get("max_length")
    if mx and len(value) > mx:
        return False, f"exceeds max_length ({mx})"
    mn = field_def.get("min_length")
    if mn and len(value) < mn:
        return False, f"below min_length ({mn})"
    pattern = field_def.get("pattern")
    if pattern and not re.match(pattern, value):
        return False, f"does not match pattern {pattern}"
    return True, value


def _validate_number(value: Any, field_def: dict) -> tuple[bool, Any]:
    if isinstance(value, bool):
        return False, "expected number, got bool"
    if not isinstance(value, (int, float)):
        return False, "expected number"
    mn = field_def.get("min")
    if mn is not None and value < mn:
        return False, f"below minimum ({mn})"
    mx = field_def.get("max")
    if mx is not None and value > mx:
        return False, f"exceeds maximum ({mx})"
    return True, value


def _validate_boolean(value: Any, _: dict) -> tuple[bool, Any]:
    if not isinstance(value, bool):
        return False, "expected boolean"
    return True, value


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DT = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def _validate_date(value: Any, _: dict) -> tuple[bool, Any]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return True, value.isoformat()
    if isinstance(value, str) and _ISO_DATE.match(value):
        try:
            date.fromisoformat(value)
            return True, value
        except ValueError:
            pass
    return False, "expected ISO date (YYYY-MM-DD)"


def _validate_datetime(value: Any, _: dict) -> tuple[bool, Any]:
    if isinstance(value, datetime):
        return True, value.isoformat()
    if isinstance(value, str) and _ISO_DT.match(value):
        try:
            datetime.fromisoformat(value)
            return True, value
        except ValueError:
            pass
    return False, "expected ISO datetime"


_URL_RE = re.compile(r"^https?://\S+$")


def _validate_url(value: Any, _: dict) -> tuple[bool, Any]:
    if isinstance(value, str) and _URL_RE.match(value):
        return True, value
    return False, "expected a valid URL (http/https)"


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(value: Any, _: dict) -> tuple[bool, Any]:
    if isinstance(value, str) and _EMAIL_RE.match(value):
        return True, value.lower()
    return False, "expected a valid email"


def _validate_enum(value: Any, field_def: dict) -> tuple[bool, Any]:
    options = field_def.get("options", [])
    if value not in options:
        return False, f"must be one of {options}"
    return True, value


def _validate_tags(value: Any, _: dict) -> tuple[bool, Any]:
    if isinstance(value, str):
        value = [t.strip() for t in value.split(",") if t.strip()]
    if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
        return False, "expected list of strings"
    return True, value


def _validate_markdown(value: Any, _: dict) -> tuple[bool, Any]:
    if not isinstance(value, str):
        return False, "expected string (markdown)"
    return True, value


def _validate_relation(value: Any, field_def: dict) -> tuple[bool, Any]:
    many = field_def.get("many", False)
    any = field_def.get("target") == "*"

    if any:
        if many:
            if isinstance(value, list) and all(
                isinstance(v, (str, int)) for v in value
            ):
                return True, value
            return False, "expected list of IDs or homebase:// references"
        if isinstance(value, (str, int)):
            return True, value
        return False, "expected a single ID or homebase:// reference"

    if many:
        if isinstance(value, list) and all(isinstance(v, (str, int)) for v in value):
            return True, value
        return False, "expected list of IDs"
    if isinstance(value, (str, int)):
        return True, value
    return False, "expected a single ID"


def _validate_json(value: Any, _: dict) -> tuple[bool, Any]:
    # Accept anything JSON-serialisable.
    try:
        json.dumps(value)
        return True, value
    except TypeError, ValueError:
        return False, "value is not JSON-serialisable"


def _validate_list(value: Any, field_def: dict) -> tuple[bool, Any]:
    if not isinstance(value, list):
        return False, "expected list"
    item_type = field_def.get("item_type", "string")
    validator = _VALIDATORS.get(item_type, _validate_string)
    cleaned = []
    for i, item in enumerate(value):
        ok, result = validator(item, field_def)
        if not ok:
            return False, f"item [{i}]: {result}"
        cleaned.append(result)
    return True, cleaned


_VALIDATORS: dict[str, Any] = {
    FieldType.STRING: _validate_string,
    FieldType.NUMBER: _validate_number,
    FieldType.BOOLEAN: _validate_boolean,
    FieldType.DATE: _validate_date,
    FieldType.DATETIME: _validate_datetime,
    FieldType.URL: _validate_url,
    FieldType.EMAIL: _validate_email,
    FieldType.ENUM: _validate_enum,
    FieldType.TAGS: _validate_tags,
    FieldType.MARKDOWN: _validate_markdown,
    FieldType.RELATION: _validate_relation,
    FieldType.JSON: _validate_json,
    FieldType.LIST: _validate_list,
}


# Schema loader & manager


class SchemaError(Exception):
    """Raised when the schema definition itself is invalid."""


class ValidationError(Exception):
    """Raised when a document fails validation against its entity schema."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(f"Validation failed: {errors}")


class FieldDef:
    """Parsed field definition with helper properties."""

    __slots__ = (
        "name",
        "raw",
        "type",
        "required",
        "default",
        "many",
        "target",
        "options",
        "searchable",
        "hidden",
        "related_name",
        "label",
    )

    def __init__(self, name: str, raw: dict):
        self.name = name
        self.raw = raw
        self.type = FieldType(raw.get("type", "string"))
        self.required = raw.get("required", False)
        self.default = raw.get("default")
        self.many = raw.get("many", False)
        self.target = raw.get("target")  # relation target entity
        self.related_name = raw.get("related_name")  # optional reverse relation name
        self.options = raw.get("options", [])  # enum options
        self.searchable = raw.get("searchable", True)
        self.hidden = raw.get("hidden", False)  # hide from list views
        self.label = raw.get("label", name.replace("_", " ").title())

    @property
    def is_relation(self) -> bool:
        return self.type == FieldType.RELATION

    def to_dict(self) -> dict:
        """JSON-safe representation for the frontend."""
        d: dict[str, Any] = {
            "type": self.type.value,
            "required": self.required,
            "label": self.label,
        }
        if self.default is not None:
            d["default"] = self.default
        if self.options:
            d["options"] = self.options
        if self.target:
            d["target"] = self.target
            d["many"] = self.many
        if self.hidden:
            d["hidden"] = True
        if self.related_name:
            d["related_name"] = self.related_name
        # Forward any extra keys the user put in the field def (display hints etc.)

        extras = {
            k: v
            for k, v in self.raw.items()
            if k
            not in {
                "type",
                "required",
                "default",
                "options",
                "target",
                "many",
                "searchable",
                "hidden",
                "related_name",
                "label",
            }
        }
        d.update(extras)
        return d


class EntityDef:
    """Parsed entity definition."""

    __slots__ = (
        "name",
        "raw",
        "fields",
        "icon",
        "label",
        "plural",
        "list_columns",
        "sort_default",
        "display_field",
        "junction",
        "color_id",
    )

    def __init__(self, name: str, raw: dict):
        self.name = name
        self.raw = raw
        self.icon = raw.get("icon", "box")
        self.label = raw.get("label", name.replace("_", " ").title())
        self.plural = raw.get("plural", self.label + "s")
        self.list_columns = raw.get("list_columns", [])
        self.junction = raw.get("junction", None)
        self.color_id = raw.get("color_id", None)

        raw_fields = raw.get("fields", {})
        if not raw_fields:
            raise SchemaError(f"Entity '{name}' has no fields defined")
        self.fields: dict[str, FieldDef] = {
            fname: FieldDef(fname, fdef if isinstance(fdef, dict) else {"type": fdef})
            for fname, fdef in raw_fields.items()
        }

        self.display_field = raw.get(
            "display_field", self.fields.keys().__iter__().__next__()
        )  # first field by default
        self.sort_default = raw.get("sort_default", self.display_field)

        # If list_columns is empty, auto-generate: required fields first, then first 4.
        if not self.list_columns:
            self.list_columns = [
                f.name
                for f in sorted(
                    self.fields.values(),
                    key=lambda f: (not f.required, f.name),
                )
                if not f.hidden
            ][:5]

        if self.junction:
            if not isinstance(self.junction, dict):
                raise SchemaError(
                    f"Entity '{name}': junction must be a dict with 'left' and 'right'"
                )
            if "left" not in self.junction or "left" not in self.junction:
                raise SchemaError(
                    f"Entity '{name}': junction must contain 'entities' and 'fields' keys"
                )

    @property
    def required_fields(self) -> list[FieldDef]:
        return [f for f in self.fields.values() if f.required]

    @property
    def relation_fields(self) -> list[FieldDef]:
        return [f for f in self.fields.values() if f.is_relation]

    @property
    def searchable_fields(self) -> list[FieldDef]:
        return [
            f
            for f in self.fields.values()
            if f.searchable
            and f.type
            in (
                FieldType.STRING,
                FieldType.MARKDOWN,
                FieldType.URL,
                FieldType.EMAIL,
                FieldType.TAGS,
            )
        ]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "icon": self.icon,
            "label": self.label,
            "plural": self.plural,
            "display_field": self.display_field,
            "sort_default": self.sort_default,
            "list_columns": self.list_columns,
            "fields": {fname: fdef.to_dict() for fname, fdef in self.fields.items()},
            "junction": self.junction,
            "color_id": self.color_id,
        }


class Schema:
    """
    The main schema manager.

    Usage:
        schema = Schema.from_file("schema.yaml")
        schema.validate("service", {"name": "Plex", "status": "running"})
        frontend_payload = schema.to_dict()
    """

    def __init__(self, raw: dict):
        raw_entities = raw.get("entities", {})
        if not raw_entities:
            raise SchemaError(
                "Schema must define at least one entity under 'entities:'"
            )

        self.meta: dict = raw.get("meta", {})  # optional top-level metadata
        self.globals: dict = raw.get("globals", {})  # shared defaults / settings

        self.entities: dict[str, EntityDef] = {}
        for ename, edef in raw_entities.items():
            self.entities[ename] = EntityDef(ename, edef)

        self._validate_relations()
        self._build_reverse_relations()

        # Assign colors
        for i, ename in enumerate(self.entities):
            if not self.entities[ename].color_id:
                self.entities[ename].color_id = (
                    i % MAX_COLORS
                ) + 1  # cycle through 8 colors

    # ── Loaders ───────────────────────────────

    @classmethod
    def from_file(cls, path: str | Path) -> "Schema":
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        if path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(text)
        elif path.suffix == ".json":
            data = json.loads(text)
        else:
            # Try YAML first, fall back to JSON.
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError:
                data = json.loads(text)
        return cls(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Schema":
        return cls(data)

    # ── Validation ────────────────────────────

    def validate(
        self,
        entity_type: str,
        doc: dict,
        *,
        partial: bool = False,
    ) -> dict:
        """
        Validate a document against its entity schema.

        Args:
            entity_type: Key from schema.yaml entities.
            doc:         The document (dict) to validate.
            partial:     If True, skip required-field checks (for PATCH updates).

        Returns:
            Cleaned document with defaults applied and values coerced.

        Raises:
            SchemaError:     If entity_type is unknown.
            ValidationError: If any field fails validation.
        """
        entity = self._get_entity(entity_type)
        errors: dict[str, str] = {}
        cleaned: dict[str, Any] = {}

        for fname, fdef in entity.fields.items():
            value = doc.get(fname)

            # Handle missing fields.
            if value is None:
                if fdef.required and not partial:
                    errors[fname] = "required"
                elif fdef.default is not None:
                    cleaned[fname] = fdef.default
                # else: field simply absent — fine.
                continue

            # Run the type validator.
            validator = _VALIDATORS.get(fdef.type, _validate_string)
            ok, result = validator(value, fdef.raw)
            if ok:
                cleaned[fname] = result
            else:
                errors[fname] = result

        # Reject unknown fields (configurable: strict mode).
        if self.globals.get("strict_fields", False):
            extra = set(doc.keys()) - set(entity.fields.keys())
            for key in extra:
                errors[key] = "unknown field"
        else:
            # Permissive: pass through unknown fields untouched.
            for key, val in doc.items():
                if key not in entity.fields and key not in cleaned:
                    cleaned[key] = val

        if errors:
            raise ValidationError(errors)

        return cleaned

    # ── Relationship helpers ──────────────────

    def get_relations_for(self, entity_type: str) -> list[dict]:
        """Forward relations: fields on this entity that point elsewhere."""
        entity = self._get_entity(entity_type)
        return [
            {"field": f.name, "target": f.target, "many": f.many}
            for f in entity.relation_fields
        ]

    def get_reverse_relations_for(self, entity_type: str) -> list[dict]:
        """Reverse relations: other entities that point to this one."""
        return self._reverse_relations.get(entity_type, [])

    # ── Schema export ─────────────────────────

    def entity_names(self) -> list[str]:
        return list(self.entities.keys())

    def get_entity(self, entity_type: str) -> EntityDef:
        return self._get_entity(entity_type)

    def to_dict(self) -> dict:
        """Full schema payload for GET /api/schema."""
        return {
            "meta": self.meta,
            "globals": self.globals,
            "entities": {
                ename: edef.to_dict() for ename, edef in self.entities.items()
            },
            "relations": {
                ename: {
                    "forward": self.get_relations_for(ename),
                    "reverse": self.get_reverse_relations_for(ename),
                }
                for ename in self.entities
            },
        }

    # ── Internals ─────────────────────────────

    def _get_entity(self, entity_type: str) -> EntityDef:
        if entity_type not in self.entities:
            raise SchemaError(
                f"Unknown entity type '{entity_type}'. "
                f"Available: {list(self.entities.keys())}"
            )
        return self.entities[entity_type]

    def _validate_relations(self) -> None:
        """Ensure all relation targets reference existing entities."""
        for ename, edef in self.entities.items():
            for fdef in edef.relation_fields:
                if fdef.target == "*":
                    continue  # wildcard target allowed
                if fdef.target not in self.entities:
                    raise SchemaError(
                        f"Entity '{ename}', field '{fdef.name}': "
                        f"relation target '{fdef.target}' does not exist"
                    )

    def _build_reverse_relations(self) -> None:
        """Pre-compute reverse relation map for fast lookups."""
        self._reverse_relations: dict[str, list[dict]] = {
            ename: [] for ename in self.entities
        }
        for ename, edef in self.entities.items():
            for fdef in edef.relation_fields:
                # TODO fix type warning
                if fdef.target == "*":
                    continue  # skip wildcard targets
                self._reverse_relations[fdef.target].append(  # type: ignore
                    {
                        "entity": ename,
                        "field": fdef.name,
                        "many": fdef.many,
                        "related_name": fdef.related_name,
                    }
                )
