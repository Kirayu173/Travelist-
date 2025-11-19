import json
import logging
import math
from contextlib import contextmanager
from typing import Any, Iterable, List, Optional, Tuple

from pydantic import BaseModel

try:
    from psycopg.types.json import Json
    from psycopg_pool import ConnectionPool

    PSYCOPG_VERSION = 3
except ImportError:  # pragma: no cover - psycopg2 fallback
    from psycopg2.extras import Json  # type: ignore
    from psycopg2.pool import ThreadedConnectionPool as ConnectionPool  # type: ignore

    PSYCOPG_VERSION = 2

from mem0.vector_stores.base import VectorStoreBase

logger = logging.getLogger(__name__)


class OutputData(BaseModel):
    id: Optional[str]
    score: Optional[float]
    payload: Optional[dict]


class PGArray(VectorStoreBase):
    """Fallback Postgres vector store that使用 double precision[] 存储向量."""

    def __init__(
        self,
        connection_string: str,
        collection_name: str,
        embedding_model_dims: int,
        minconn: int = 1,
        maxconn: int = 5,
    ) -> None:
        self.collection_name = collection_name
        self.embedding_model_dims = embedding_model_dims
        if PSYCOPG_VERSION == 3:
            self.connection_pool = ConnectionPool(
                conninfo=connection_string,
                min_size=minconn,
                max_size=maxconn,
                open=True,
            )
        else:  # pragma: no cover - psycopg2 fallback
            self.connection_pool = ConnectionPool(
                minconn=minconn,
                maxconn=maxconn,
                dsn=connection_string,
            )
        self.create_col(collection_name, embedding_model_dims, None)

    @contextmanager
    def _get_cursor(self, commit: bool = False):
        if PSYCOPG_VERSION == 3:
            with self.connection_pool.connection() as conn:
                with conn.cursor() as cur:
                    try:
                        yield cur
                        if commit:
                            conn.commit()
                    except Exception:
                        conn.rollback()
                        raise
        else:  # pragma: no cover - psycopg2 fallback
            conn = self.connection_pool.getconn()
            cur = conn.cursor()
            try:
                yield cur
                if commit:
                    conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()
                self.connection_pool.putconn(conn)

    def create_col(self, name=None, vector_size=None, distance=None):
        with self._get_cursor(commit=True) as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.collection_name} (
                    id UUID PRIMARY KEY,
                    vector DOUBLE PRECISION[],
                    payload JSONB,
                    norm DOUBLE PRECISION
                )
                """
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS {self.collection_name}_payload_user_idx ON {self.collection_name} ((payload ->> 'user_id'))"
            )

    def delete_col(self):
        with self._get_cursor(commit=True) as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.collection_name}")

    def col_info(self):
        with self._get_cursor() as cur:
            cur.execute(
                f"SELECT COUNT(1) FROM {self.collection_name}",
            )
            count = cur.fetchone()[0]
        return {"name": self.collection_name, "count": count}

    def list_cols(self):
        with self._get_cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )
            return [row[0] for row in cur.fetchall()]

    def reset(self):
        self.delete_col()
        self.create_col(self.collection_name, self.embedding_model_dims, None)

    def insert(self, vectors, payloads=None, ids=None):
        rows = []
        for vector, payload, vector_id in zip(vectors, payloads or [], ids or []):
            payload = payload or {}
            rows.append(
                (
                    vector_id,
                    vector,
                    payload,
                    self._vector_norm(vector),
                )
            )
        if not rows:
            return

        with self._get_cursor(commit=True) as cur:
            for row in rows:
                cur.execute(
                    f"""
                    INSERT INTO {self.collection_name} (id, vector, payload, norm)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id)
                    DO UPDATE SET vector = EXCLUDED.vector, payload = EXCLUDED.payload, norm = EXCLUDED.norm
                    """,
                    (row[0], row[1], Json(row[2]), row[3]),
                )

    def search(self, query, vectors, limit=5, filters=None):
        query_vector = vectors or []
        query_norm = self._vector_norm(query_vector)
        if not query_vector or not query_norm:
            return []

        where_sql, params = self._build_filters(filters)
        sql = f"SELECT id, vector, payload, norm FROM {self.collection_name}"
        if where_sql:
            sql += f" WHERE {where_sql}"

        with self._get_cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        scored: List[OutputData] = []
        for vector_id, vector, payload, norm in rows:
            dot = sum(a * b for a, b in zip(vector, query_vector))
            denom = (norm or self._vector_norm(vector)) * query_norm
            if not denom:
                continue
            score = dot / denom
            scored.append(
                OutputData(
                    id=str(vector_id),
                    score=score,
                    payload=(
                        payload if isinstance(payload, dict) else json.loads(payload)
                    ),
                )
            )

        scored.sort(key=lambda item: item.score or 0.0, reverse=True)
        return scored[:limit]

    def delete(self, vector_id):
        if not vector_id:
            return
        vector_ids = (
            vector_id
            if isinstance(vector_id, Iterable)
            and not isinstance(vector_id, (str, bytes))
            else [vector_id]
        )
        with self._get_cursor(commit=True) as cur:
            cur.execute(
                f"DELETE FROM {self.collection_name} WHERE id = ANY(%s)",
                (vector_ids,),
            )

    def update(self, vector_id, vector=None, payload=None):
        if vector is None and payload is None:
            return
        with self._get_cursor(commit=True) as cur:
            cur.execute(
                f"""
                UPDATE {self.collection_name}
                SET
                    vector = COALESCE(%s, vector),
                    payload = COALESCE(%s, payload),
                    norm = COALESCE(%s, norm)
                WHERE id = %s
                """,
                (
                    vector,
                    Json(payload) if payload is not None else None,
                    self._vector_norm(vector) if vector is not None else None,
                    vector_id,
                ),
            )

    def get(self, vector_id):
        with self._get_cursor() as cur:
            cur.execute(
                f"SELECT payload FROM {self.collection_name} WHERE id = %s",
                (vector_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def list(self, filters=None, limit=None):
        where_sql, params = self._build_filters(filters)
        sql = f"SELECT id, payload FROM {self.collection_name}"
        if where_sql:
            sql += f" WHERE {where_sql}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self._get_cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def _vector_norm(self, vector: List[float]) -> float:
        return math.sqrt(sum(val * val for val in vector)) if vector else 0.0

    def _build_filters(self, filters: dict | None) -> Tuple[str, List[Any]]:
        if not filters:
            return "", []
        clauses: List[str] = []
        params: List[Any] = []
        for key, value in filters.items():
            if value is None:
                continue
            clauses.append("(payload ->> %s) = %s")
            params.extend([key, str(value)])
        return " AND ".join(clauses), params
