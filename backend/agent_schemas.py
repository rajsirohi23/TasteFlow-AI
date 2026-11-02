"""Shared request/response models for the agents (one source of truth)."""
from pydantic import BaseModel, Field


class MenuRecommendationRequest(BaseModel):
    budget: int | None = Field(default=None, ge=0)
    diet: str | None = Field(default=None, min_length=1, max_length=50)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    spice_level: str | None = Field(default=None, min_length=1, max_length=30)
    # "not too spicy" means "at most Medium": a ceiling, not an exact match.
    max_spice_level: str | None = Field(default=None, min_length=1, max_length=30)
    exclude_ingredients: list[str] = Field(default_factory=list, max_length=10)
    protein_focus: bool = False
    limit: int = Field(default=5, ge=1, le=20)
