"""pandera schema contracts for the published tables (dimensions 1 & 3).

Complements the DuckDB checks in ``qa.py`` with declarative column dtype/range/enum contracts
that double as consumer-facing documentation. Validated with ``lazy=True`` to collect all errors.
"""
from __future__ import annotations

import pandas as pd
import pandera.pandas as pa

STATUS_ENUM = ["FT", "AET", "PEN", "AWD", "WO", "NS", "PST", "CANC", "ABD", "SUSP", "OTHER"]

fixtures_schema = pa.DataFrameSchema(
    {
        "id": pa.Column(nullable=False, unique=True, coerce=True),
        "date_utc": pa.Column("datetime64[ns]", nullable=False, coerce=True),
        "league_id": pa.Column(nullable=False, coerce=True),
        "home_team_id": pa.Column(nullable=False, coerce=True),
        "away_team_id": pa.Column(nullable=False, coerce=True),
        "goals_home": pa.Column(float, pa.Check.ge(0), nullable=True, coerce=True),
        "goals_away": pa.Column(float, pa.Check.ge(0), nullable=True, coerce=True),
        "status_norm": pa.Column(str, pa.Check.isin(STATUS_ENUM), nullable=False),
        "is_played": pa.Column(bool, nullable=True, coerce=True),
    },
    strict=False, coerce=True,
)

match_stats_schema = pa.DataFrameSchema(
    {
        "fixture_id": pa.Column(nullable=False, coerce=True),
        "home_xg": pa.Column(float, pa.Check.in_range(0, 6), nullable=True, coerce=True),
        "away_xg": pa.Column(float, pa.Check.in_range(0, 6), nullable=True, coerce=True),
        "home_possession": pa.Column(float, pa.Check.in_range(0, 100), nullable=True, coerce=True),
        "away_possession": pa.Column(float, pa.Check.in_range(0, 100), nullable=True, coerce=True),
        "home_pass_accuracy": pa.Column(float, pa.Check.in_range(0, 100), nullable=True, coerce=True),
        "xg_covered": pa.Column(bool, nullable=True, coerce=True),
    },
    strict=False, coerce=True,
)

odds_schema = pa.DataFrameSchema(
    {
        "fixture_id": pa.Column(nullable=False, coerce=True),
        "home_win": pa.Column(float, pa.Check.gt(1), nullable=True, coerce=True),
        "draw": pa.Column(float, pa.Check.gt(1), nullable=True, coerce=True),
        "away_win": pa.Column(float, pa.Check.gt(1), nullable=True, coerce=True),
        "bookmaker": pa.Column(str, nullable=True),
    },
    strict=False, coerce=True,
)

leagues_schema = pa.DataFrameSchema(
    {"id": pa.Column(nullable=False, unique=True, coerce=True),
     "name": pa.Column(str, nullable=False),
     "country": pa.Column(str, nullable=True)},
    strict=False, coerce=True,
)

SCHEMAS = {
    "fixtures": fixtures_schema, "match_stats": match_stats_schema,
    "odds": odds_schema, "leagues": leagues_schema,
}


def validate(table: str, df: pd.DataFrame) -> tuple[bool, str]:
    schema = SCHEMAS.get(table)
    if schema is None:
        return True, "no schema"
    try:
        schema.validate(df, lazy=True)
        return True, "ok"
    except pa.errors.SchemaErrors as e:
        return False, f"{len(e.failure_cases)} failure cases; sample: {e.failure_cases.head(3).to_dict('records')}"
