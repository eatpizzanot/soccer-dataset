"""Shared DuckDB staging helpers."""
from __future__ import annotations

import duckdb

from pipeline import config as c


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(c.STAGING_DB), read_only=read_only)
    con.execute("PRAGMA threads=4")
    return con


def csv_view(con, table: str, name: str | None = None) -> None:
    name = name or table
    path = (c.CSV_DIR / f"{table}.csv").as_posix()
    con.execute(
        f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_csv_auto('{path}', sample_size=-1)"
    )


def pq_view(con, table: str, name: str | None = None) -> None:
    name = name or table
    path = (c.PARQUET_DIR / f"{table}.parquet").as_posix()
    con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{path}')")
