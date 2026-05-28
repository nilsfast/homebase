import pytest
from homebase.core.schema import Schema, ValidationError

sample = {
    "entities": {
        "service": {
            "icon": "server",
            "fields": {
                "name": {"type": "string", "required": True},
                "url": {"type": "url"},
                "status": {
                    "type": "enum",
                    "options": ["running", "stopped", "deprecated"],
                },
                "host": {"type": "relation", "target": "host"},
                "notes": {"type": "markdown"},
                "tags": {"type": "tags"},
            },
            "list_columns": ["name", "status", "url", "host"],
        },
        "host": {
            "icon": "hard-drive",
            "fields": {
                "name": {"type": "string", "required": True},
                "ip": {"type": "string"},
                "os": {"type": "string"},
                "ram_gb": {"type": "number"},
                "role": {
                    "type": "enum",
                    "options": ["hypervisor", "bare-metal", "vm", "container"],
                },
            },
        },
        "credential": {
            "icon": "key",
            "fields": {
                "name": {"type": "string", "required": True},
                "service": {"type": "relation", "target": "service"},
                "notes": {"type": "markdown"},
            },
        },
    },
}


def test_schema_validation():
    schema = Schema.from_dict(sample)

    # Validate a good document.
    cleaned = schema.validate(
        "service",
        {
            "name": "Plex",
            "url": "http://192.168.1.10:32400",
            "status": "running",
            "tags": ["media", "streaming"],
        },
    )
    assert cleaned["name"] == "Plex"

    # Show reverse relations.
    reverse_relations = schema.get_reverse_relations_for("service")
    assert isinstance(reverse_relations, list)


def test_bad_schema_validation():
    schema = Schema.from_dict(sample)
    # Validate a bad document.
    with pytest.raises(ValidationError) as _:
        schema.validate(
            "service",
            {
                "name": "Plex",
                "url": "not-a-url",
                "status": "unknown",
                "tags": "should-be-list",
            },
        )
