from typing import Optional

from pydantic import BaseModel, Field


class RerankerConfig(BaseModel):
    """Configuration schema for rerankers."""

    provider: str = Field(
        default="cohere",
        description="Reranker provider (e.g., 'cohere', 'sentence_transformer')",
    )
    config: Optional[dict] = Field(
        default=None, description="Provider-specific reranker configuration"
    )

    model_config = {"extra": "forbid"}
