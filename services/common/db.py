from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator


def connection() -> Any:
    import psycopg
    from psycopg.rows import dict_row

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("Missing required env var: DATABASE_URL")
    return psycopg.connect(dsn, row_factory=dict_row)


@contextmanager
def cursor() -> Iterator[Any]:
    with connection() as conn, conn.cursor() as cur:
        yield cur
        conn.commit()
