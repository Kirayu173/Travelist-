from pydantic import BaseModel, Field


class PGArrayConfig(BaseModel):
    """Configuration for the Postgres array-based vector store."""

    connection_string: str = Field(..., description="PostgreSQL connection string")
    collection_name: str = Field(
        "mem0_memories",
        description="Table used to存储向量与 payload",
    )
    embedding_model_dims: int = Field(
        1536,
        description="Embedding 维度，用于创建列定义与校验",
    )
    minconn: int = Field(1, description="连接池最小连接数")
    maxconn: int = Field(5, description="连接池最大连接数")
