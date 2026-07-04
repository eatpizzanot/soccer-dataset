#!/usr/bin/env python3
"""Load the curated parquet dataset into the probodds_soccer Postgres DB (runs on the box).

Uses DuckDB's postgres extension to stream parquet -> Postgres, then applies primary keys,
foreign keys and indexes. Reads the connection from /root/probodds_soccer.env (never printed).
Idempotent: drops+recreates tables. Verifies row counts against the parquet at the end.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

CURATED = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/opt/soccer-dataset/curated")
ENV = Path("/root/probodds_soccer.env")

TABLES = [
    "leagues", "teams", "players", "fixtures", "match_stats", "odds",
    "fixture_lineups", "fixture_players", "fixture_players_stats_flat", "league_catalogue",
]

CONSTRAINTS = [
    "ALTER TABLE leagues ADD PRIMARY KEY (id)",
    "ALTER TABLE teams ADD PRIMARY KEY (id)",
    "ALTER TABLE players ADD PRIMARY KEY (id)",
    "ALTER TABLE fixtures ADD PRIMARY KEY (id)",
    "ALTER TABLE fixture_players ADD PRIMARY KEY (id)",
    "CREATE INDEX ix_fixtures_league ON fixtures(league_id)",
    "CREATE INDEX ix_fixtures_date ON fixtures(date_utc)",
    "CREATE INDEX ix_fixtures_home ON fixtures(home_team_id)",
    "CREATE INDEX ix_fixtures_away ON fixtures(away_team_id)",
    "CREATE INDEX ix_match_stats_fixture ON match_stats(fixture_id)",
    "CREATE INDEX ix_odds_fixture ON odds(fixture_id)",
    "CREATE INDEX ix_lineups_fixture ON fixture_lineups(fixture_id)",
    "CREATE INDEX ix_fp_fixture ON fixture_players(fixture_id)",
    "CREATE INDEX ix_fp_player ON fixture_players(player_id)",
    "CREATE INDEX ix_fps_fixture ON fixture_players_stats_flat(fixture_id)",
    "ALTER TABLE fixtures ADD CONSTRAINT fk_fixtures_league FOREIGN KEY (league_id) REFERENCES leagues(id)",
    "ALTER TABLE fixtures ADD CONSTRAINT fk_fixtures_home FOREIGN KEY (home_team_id) REFERENCES teams(id)",
    "ALTER TABLE fixtures ADD CONSTRAINT fk_fixtures_away FOREIGN KEY (away_team_id) REFERENCES teams(id)",
    "ALTER TABLE match_stats ADD CONSTRAINT fk_ms_fixture FOREIGN KEY (fixture_id) REFERENCES fixtures(id)",
    "ALTER TABLE odds ADD CONSTRAINT fk_odds_fixture FOREIGN KEY (fixture_id) REFERENCES fixtures(id)",
    "ALTER TABLE fixture_lineups ADD CONSTRAINT fk_lu_fixture FOREIGN KEY (fixture_id) REFERENCES fixtures(id)",
    "ALTER TABLE fixture_players ADD CONSTRAINT fk_fp_fixture FOREIGN KEY (fixture_id) REFERENCES fixtures(id)",
    "ALTER TABLE fixture_players ADD CONSTRAINT fk_fp_player FOREIGN KEY (player_id) REFERENCES players(id)",
]


def conn_str() -> str:
    env = {}
    for line in ENV.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return (f"host={env['PGHOST']} port={env['PGPORT']} dbname={env['PGDATABASE']} "
            f"user={env['PGUSER']} password={env['PGPASSWORD']}")


def main() -> None:
    cs = conn_str()
    con = duckdb.connect()
    con.execute("INSTALL postgres; LOAD postgres;")
    con.execute(f"ATTACH '{cs}' AS pg (TYPE postgres)")

    for t in TABLES:
        src = (CURATED / f"{t}.parquet").as_posix()
        con.execute(f"DROP TABLE IF EXISTS pg.{t} CASCADE")
        con.execute(f"CREATE TABLE pg.{t} AS SELECT * FROM read_parquet('{src}')")
        pc = con.execute(f"SELECT count(*) FROM pg.{t}").fetchone()[0]
        fc = con.execute(f"SELECT count(*) FROM read_parquet('{src}')").fetchone()[0]
        status = "ok" if pc == fc else "MISMATCH"
        print(f"  loaded {t:<30} pg={pc:>10,} parquet={fc:>10,} {status}", flush=True)

    ok, fail = 0, 0
    for ddl in CONSTRAINTS:
        try:
            con.execute(f"CALL postgres_execute('pg', $q${ddl}$q$)")
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  constraint skipped: {ddl.split(' ADD ')[0][:40]}... ({str(e)[:60]})")
    print(f"constraints applied: {ok} ok, {fail} skipped")
    print("grant read-only:")
    con.execute("CALL postgres_execute('pg', 'GRANT SELECT ON ALL TABLES IN SCHEMA public TO soccer_ro')")
    con.close()
    print("migration complete.")


if __name__ == "__main__":
    main()
