"""Phase 4b - ingest fixtures (and teams) for leagues/seasons from API-Football.

Fixtures-first strategy: one cheap call per (league, season) yields goals/status/teams -> BTTS
labels + coverage, and discovers new teams. Per-fixture stats/lineups/players are a separate,
more expensive backfill (phase4_ingest_stats). Results are appended idempotently to
``raw_ingest_*`` tables in build/staging.duckdb (dedup by api id), so re-runs are safe.
"""
from __future__ import annotations

import io
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pipeline import config as c  # noqa: E402
from pipeline import staging  # noqa: E402
from pipeline.apifootball import ApiFootball  # noqa: E402

DDL_FIX = """
CREATE TABLE IF NOT EXISTS raw_ingest_fixtures (
  api_football_id BIGINT PRIMARY KEY, date_utc TIMESTAMP, status VARCHAR,
  league_af_id BIGINT, league_name VARCHAR, country VARCHAR, season INTEGER, round VARCHAR,
  home_team_af_id BIGINT, home_team_name VARCHAR, away_team_af_id BIGINT, away_team_name VARCHAR,
  goals_home INTEGER, goals_away INTEGER, ht_home INTEGER, ht_away INTEGER,
  referee_name VARCHAR, ingested_at TIMESTAMP
)"""
DDL_TEAM = """
CREATE TABLE IF NOT EXISTS raw_ingest_teams (
  api_football_id BIGINT PRIMARY KEY, name VARCHAR, country VARCHAR, ingested_at TIMESTAMP
)"""


def _parse_dt(s: str) -> str | None:
    # API returns e.g. 2024-08-16T19:00:00+00:00 -> store UTC-naive
    if not s:
        return None
    return s.replace("T", " ")[:19]


def ingest(pairs: list[tuple[int, int]], label: str = "") -> dict:
    """pairs: list of (af_league_id, season)."""
    con = staging.connect()
    con.execute(DDL_FIX)
    con.execute(DDL_TEAM)
    af = ApiFootball()
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    n_fix = 0
    for i, (lid, season) in enumerate(pairs, 1):
        resp = af.get("fixtures", {"league": lid, "season": season})
        frows, trows = [], {}
        for it in resp:
            fx, lg, tm, gl = it["fixture"], it["league"], it["teams"], it["goals"]
            sc = it.get("score", {}) or {}
            ht = (sc.get("halftime") or {})
            frows.append((
                fx["id"], _parse_dt(fx.get("date")), (fx.get("status") or {}).get("short"),
                lg["id"], lg.get("name"), lg.get("country"), lg.get("season"), lg.get("round"),
                tm["home"]["id"], tm["home"]["name"], tm["away"]["id"], tm["away"]["name"],
                gl.get("home"), gl.get("away"), ht.get("home"), ht.get("away"),
                fx.get("referee"), now,
            ))
            for side in ("home", "away"):
                t = tm[side]
                trows[t["id"]] = (t["id"], t["name"], lg.get("country"), now)
        if frows:
            con.executemany(
                "INSERT OR REPLACE INTO raw_ingest_fixtures VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", frows)
            con.executemany("INSERT OR REPLACE INTO raw_ingest_teams VALUES (?,?,?,?)", list(trows.values()))
            n_fix += len(frows)
        if i % 20 == 0 or i == len(pairs):
            print(f"  [{label}] {i}/{len(pairs)} league-seasons, {n_fix} fixtures, {af.request_count} api calls", flush=True)
    total = con.execute("SELECT count(*) FROM raw_ingest_fixtures").fetchone()[0]
    con.close()
    return {"pairs": len(pairs), "fixtures_ingested_this_run": n_fix,
            "raw_ingest_fixtures_total": total, "api_calls": af.request_count}


if __name__ == "__main__":
    # smoke test: EPL 2024 (af league 39)
    import json
    print(json.dumps(ingest([(39, 2024)], label="smoke"), indent=2))
