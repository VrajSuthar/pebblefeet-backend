from typing import ClassVar, Generic, Self, TypeVar

from pydantic import BaseModel, Field, model_validator

T = TypeVar("T")

MAX_PAGE_SIZE = 50


class PageQuerySchema(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=MAX_PAGE_SIZE)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PageSchema(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class PartialUpdateSchema(BaseModel):
    """PATCH body: only fields that were sent are applied."""

    # Columns that are NOT NULL in the database, so an explicit null is rejected
    non_nullable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def reject_nulls(self) -> Self:
        cleared = sorted(
            f for f in self.model_fields_set & self.non_nullable if getattr(self, f) is None
        )
        if cleared:
            raise ValueError(f"{', '.join(cleared)} cannot be null")
        return self

    def changes(self) -> dict:
        return self.model_dump(exclude_unset=True)
