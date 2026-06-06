# Document Schema
# A document has a title, and a series of steps which can be either text or markdown
# It also has a list of related entities (represented as homebase:// links)

from typing import Annotated

from pydantic import BaseModel, Field


class Document(BaseModel):
    title: str = Field(..., description="Title of the document.")
    content: str = Field(..., description="Markdown content of the document.")
    related_entities: list[
        Annotated[
            str, Field(description="List of related entities as homebase:// links.")
        ]
    ] = Field(default_factory=list)
