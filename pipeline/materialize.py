"""Materialize cleaned canonical tables to build/curated/*.parquet.

Adds the leakage guard (``known_at`` for post-match facts) at export time. Player tables are
unchanged from source, so they are copied as-is. Re-run after any ingest to refresh curated.
"""
from __future__ import annotations

import io
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pipeline import config as c  # noqa: E402
from pipeline import staging  # noqa: E402

# post-match facts become known ~ match end (kickoff + 105 min); pre-match odds at kickoff.
EXPORTS = {
    "fixtures": "SELECT * FROM cln_fixtures",
    "match_stats": (
        "SELECT m.*, (f.date_utc + INTERVAL 105 MINUTE) AS known_at "
        "FROM cln_match_stats m JOIN cln_fixtures f ON f.id = m.fixture_id"
    ),
    "odds": "SELECT o.*, f.date_utc AS known_at FROM cln_odds o JOIN cln_fixtures f ON f.id = o.fixture_id",
    "fixture_lineups": "SELECT * FROM cln_fixture_lineups",
    "teams": "SELECT * FROM cln_teams",
    "players": "SELECT * FROM cln_players",
    "leagues": "SELECT * FROM cln_leagues",
}


def main() -> None:
    con = staging.connect()
    c.CURATED_DIR.mkdir(parents=True, exist_ok=True)
    for name, sql in EXPORTS.items():
        out = (c.CURATED_DIR / f"{name}.parquet").as_posix()
        con.execute(f"COPY ({sql}) TO '{out}' (FORMAT PARQUET)")
        n = con.execute(f"SELECT count(*) FROM ({sql})").fetchone()[0]
        print(f"  wrote {name:<18} {n:>10,} rows")
    # fixture_players: clean implausible minutes/rating anomalies at export
    src_fp = (c.PARQUET_DIR / "fixture_players.parquet").as_posix()
    out_fp = (c.CURATED_DIR / "fixture_players.parquet").as_posix()
    con.execute(f"""
      COPY (SELECT * REPLACE(
        CASE WHEN minutes BETWEEN 0 AND 130 THEN minutes ELSE NULL END AS minutes,
        CASE WHEN rating BETWEEN 0 AND 10 THEN rating ELSE NULL END AS rating)
      FROM read_parquet('{src_fp}')) TO '{out_fp}' (FORMAT PARQUET)""")
    print("  wrote fixture_players    (minutes/rating anomalies cleaned)")
    shutil.copy(c.PARQUET_DIR / "fixture_players_stats_flat.parquet", c.CURATED_DIR / "fixture_players_stats_flat.parquet")
    print("  copied fixture_players_stats_flat (unchanged from source)")
    con.close()
    print(f"curated -> {c.CURATED_DIR}")


if __name__ == "__main__":
    main()
