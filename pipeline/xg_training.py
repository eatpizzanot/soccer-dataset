"""Build xg_training.parquet - the covered-league xG training subset (shot aggregates -> xG).

Team-match long format (one row per team per match), restricted to league-seasons with real
xG coverage (xg_covered=true and that side's xG not null). Features are shot aggregates (+ a
couple of context columns); target is `xg`. Intended for a "lite xG" model that predicts xG for
the obscure tail from shot-by-zone counts. Reads build/curated (not the staging DB).
"""
from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb  # noqa: E402

from pipeline import config as c  # noqa: E402


def build() -> int:
    con = duckdb.connect()
    ms = (c.CURATED_DIR / "match_stats.parquet").as_posix()
    fx = (c.CURATED_DIR / "fixtures.parquet").as_posix()
    con.execute(f"CREATE VIEW ms AS SELECT * FROM read_parquet('{ms}')")
    con.execute(f"CREATE VIEW fx AS SELECT * FROM read_parquet('{fx}')")
    out = (c.CURATED_DIR / "xg_training.parquet").as_posix()

    def side(prefix: str, is_home: str, label: str) -> str:
        return f"""
        SELECT m.fixture_id, f.league_id, f.date_utc, f.calendar_year,
          '{label}' AS side, {is_home} AS is_home,
          m.{prefix}_shots_total AS shots_total, m.{prefix}_shots_on_goal AS shots_on_goal,
          m.{prefix}_shots_inside_box AS shots_inside_box, m.{prefix}_shots_outside_box AS shots_outside_box,
          m.{prefix}_blocked_shots AS blocked_shots, m.{prefix}_corners AS corners,
          m.{prefix}_possession AS possession, m.{prefix}_pass_accuracy AS pass_accuracy,
          m.{prefix}_xg AS xg
        FROM ms m JOIN fx f ON f.id = m.fixture_id
        WHERE m.xg_covered AND m.{prefix}_xg IS NOT NULL"""

    con.execute(f"COPY (({side('home','TRUE','home')}) UNION ALL ({side('away','FALSE','away')})) "
                f"TO '{out}' (FORMAT PARQUET)")
    return con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]


def main() -> None:
    n = build()
    print(f"xg_training.parquet: {n:,} team-match rows (covered leagues, real xG)")


if __name__ == "__main__":
    main()
