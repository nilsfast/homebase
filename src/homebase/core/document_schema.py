# Document Schema
# A document has a title, and a series of steps which can be either text or markdown
# It also has a list of related entities (represented as homebase:// links)

from typing import Annotated

from pydantic import BaseModel, Field


class Document(BaseModel):
    title: str = Field(description="Title of the document.")
    description: str = Field(description="Description of the document.")
    content: dict = Field(
        description="Content of the document, represented as a dictionary where keys are step numbers and values are either text or markdown."
    )
    related_entities: Annotated[
        list[str],
        Field(
            description="List of related entities as homebase:// links.",
            default_factory=list,
        ),
    ]
