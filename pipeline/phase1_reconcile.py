"""Phase 1 - reconcile the CSV and Parquet snapshots into unified canonical staging tables.

Findings that drive this design (verified empirically):
  * The internal ``id`` is CONSISTENT across the two snapshots (same real match -> same id),
    so we UNION by id rather than pick a single snapshot.
  * Neither snapshot is a superset: parquet holds ~64k api-fixtures the CSV lacks; the CSV
    holds ~45k the parquet lacks. The 9.96M player rows reference fixtures that are 100% in
    parquet but only 78% in CSV -> we MUST union to avoid orphaning player data.
  * Column richness differs: CSV match_stats has 13 extra columns (possession, fouls, HT
    goals, HT xG, ...); parquet fixture_lineups has +team_name and ~110k more rows.
  * A small fixture conflict set (same id, differing date/teams) is logged for audit.

Output: canonical ``stg_*`` tables in build/staging.duckdb + build/qa/phase1_report.json.
Idempotent: safe to re-run.
"""
from __future__ import annotations

import io
import json
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pipeline import config as c  # noqa: E402
from pipeline import staging  # noqa: E402

CSV = c.CSV_DIR.as_posix()
PQ = c.PARQUET_DIR.as_posix()

# match_stats columns present ONLY in the CSV snapshot
MS_CSV_ONLY_INT = [
    "home_possession", "away_possession", "home_fouls", "away_fouls",
    "home_offsides", "away_offsides", "home_pass_accuracy", "away_pass_accuracy",
    "home_goals_ht", "away_goals_ht",
]
MS_CSV_ONLY_DBL = ["home_xg_ht", "away_xg_ht"]
# match_stats columns present in BOTH snapshots (besides id/fixture_id)
MS_SHARED_INT = [
    "home_shots_total", "away_shots_total", "home_shots_on_goal", "away_shots_on_goal",
    "home_shots_inside_box", "away_shots_inside_box", "home_shots_outside_box",
    "away_shots_outside_box", "home_blocked_shots", "away_blocked_shots",
    "home_penalties", "away_penalties", "home_corners", "away_corners",
    "home_yellow_cards", "away_yellow_cards", "home_red_cards", "away_red_cards",
]
MS_SHARED_DBL = ["home_xg", "away_xg"]

RAW = {
    "raw_fx_csv": f"read_csv_auto('{CSV}/fixtures.csv', sample_size=-1)",
    "raw_fx_pq": f"read_parquet('{PQ}/fixtures.parquet')",
    "raw_ms_csv": f"read_csv_auto('{CSV}/match_stats.csv', sample_size=-1)",
    "raw_ms_pq": f"read_parquet('{PQ}/match_stats.parquet')",
    "raw_odds_csv": f"read_csv_auto('{CSV}/odds.csv', sample_size=-1)",
    "raw_odds_pq": f"read_parquet('{PQ}/odds.parquet')",
    "raw_lu_csv": f"read_csv_auto('{CSV}/fixture_lineups.csv', sample_size=-1)",
    "raw_lu_pq": f"read_parquet('{PQ}/fixture_lineups.parquet')",
    "raw_teams_csv": f"read_csv_auto('{CSV}/teams.csv', sample_size=-1)",
    "raw_teams_pq": f"read_parquet('{PQ}/teams.parquet')",
    "raw_players_csv": f"read_csv_auto('{CSV}/players.csv', sample_size=-1)",
    "raw_players_pq": f"read_parquet('{PQ}/players.parquet')",
    "raw_leagues_csv": f"read_csv_auto('{CSV}/leagues.csv', sample_size=-1)",
    "raw_leagues_pq": f"read_parquet('{PQ}/leagues.parquet')",
}


def _log(msg: str) -> None:
    print(f"[phase1] {msg}", flush=True)


def load_raw(con, force: bool = False) -> None:
    existing = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    _log("loading raw source tables (one full scan each)...")
    for name, reader in RAW.items():
        if not force and name in existing:
            continue
        con.execute(f"DROP TABLE IF EXISTS {name}")
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM {reader}")
    _log("raw tables loaded.")


def build_fixtures(con) -> None:
    norm = """
      SELECT id,
        TRY_CAST(api_football_id AS BIGINT) AS api_football_id,
        {date_expr} AS date_utc,
        TRY_CAST(league_id AS BIGINT) AS league_id,
        TRY_CAST(home_team_id AS BIGINT) AS home_team_id,
        TRY_CAST(away_team_id AS BIGINT) AS away_team_id,
        TRY_CAST(goals_home AS INTEGER) AS goals_home,
        TRY_CAST(goals_away AS INTEGER) AS goals_away,
        CAST(status AS VARCHAR) AS status,
        {ref_name} AS referee_name,
        {ref_id} AS referee_api_id,
        {created} AS created_at,
        {updated} AS updated_at
      FROM {src}
    """
    norm_csv = norm.format(
        date_expr="CAST(date AS TIMESTAMPTZ) AT TIME ZONE 'UTC'",
        ref_name="CAST(referee_name AS VARCHAR)", ref_id="TRY_CAST(referee_api_id AS BIGINT)",
        created="TRY_CAST(created_at AS TIMESTAMP)", updated="TRY_CAST(updated_at AS TIMESTAMP)",
        src="raw_fx_csv",
    )
    norm_pq = norm.format(
        date_expr="CAST(date AS TIMESTAMP)",
        ref_name="CAST(NULL AS VARCHAR)", ref_id="CAST(NULL AS BIGINT)",
        created="CAST(NULL AS TIMESTAMP)", updated="CAST(NULL AS TIMESTAMP)",
        src="raw_fx_pq",
    )
    con.execute("DROP TABLE IF EXISTS stg_fixtures")
    con.execute(f"""
    CREATE TABLE stg_fixtures AS
    WITH nc AS ({norm_csv}), np AS ({norm_pq}),
    shared AS (
      SELECT c.id, COALESCE(c.api_football_id, p.api_football_id) AS api_football_id,
        c.date_utc, c.league_id, c.home_team_id, c.away_team_id, c.goals_home, c.goals_away,
        c.status, c.referee_name, c.referee_api_id, c.created_at, c.updated_at,
        TRUE AS in_csv, TRUE AS in_pq
      FROM nc c JOIN np p ON c.id = p.id
    ),
    csv_only AS (
      SELECT c.*, TRUE AS in_csv, FALSE AS in_pq FROM nc c
      WHERE NOT EXISTS (SELECT 1 FROM np p WHERE p.id = c.id)
    ),
    pq_only AS (
      SELECT p.*, FALSE AS in_csv, TRUE AS in_pq FROM np p
      WHERE NOT EXISTS (SELECT 1 FROM nc c WHERE c.id = p.id)
    )
    SELECT * FROM shared UNION ALL SELECT * FROM csv_only UNION ALL SELECT * FROM pq_only
    """)

    # Audit: same id, disagreeing on date/teams/league/goals
    con.execute("DROP TABLE IF EXISTS audit_fixture_conflicts")
    con.execute(f"""
    CREATE TABLE audit_fixture_conflicts AS
    WITH nc AS ({norm_csv}), np AS ({norm_pq})
    SELECT c.id, c.api_football_id AS csv_api, p.api_football_id AS pq_api,
      c.date_utc AS csv_date, p.date_utc AS pq_date,
      c.home_team_id AS csv_home, p.home_team_id AS pq_home,
      c.away_team_id AS csv_away, p.away_team_id AS pq_away,
      c.league_id AS csv_league, p.league_id AS pq_league,
      c.goals_home AS csv_gh, p.goals_home AS pq_gh,
      c.goals_away AS csv_ga, p.goals_away AS pq_ga,
      CASE WHEN date_trunc('day', c.date_utc) <> date_trunc('day', p.date_utc) THEN 'date;' ELSE '' END ||
      CASE WHEN c.home_team_id<>p.home_team_id OR c.away_team_id<>p.away_team_id THEN 'teams;' ELSE '' END ||
      CASE WHEN c.league_id<>p.league_id THEN 'league;' ELSE '' END ||
      CASE WHEN c.goals_home<>p.goals_home OR c.goals_away<>p.goals_away THEN 'goals;' ELSE '' END AS conflict_kind
    FROM nc c JOIN np p ON c.id = p.id
    WHERE date_trunc('day', c.date_utc) <> date_trunc('day', p.date_utc)
       OR c.home_team_id<>p.home_team_id OR c.away_team_id<>p.away_team_id
       OR c.league_id<>p.league_id
       OR c.goals_home<>p.goals_home OR c.goals_away<>p.goals_away
    """)


def build_match_stats(con) -> None:
    def sel(pq_only: bool) -> str:
        parts = ["TRY_CAST(fixture_id AS BIGINT) AS fixture_id"]
        for col in MS_SHARED_INT:
            parts.append(f"TRY_CAST({col} AS INTEGER) AS {col}")
        for col in MS_SHARED_DBL:
            parts.append(f"TRY_CAST({col} AS DOUBLE) AS {col}")
        for col in MS_CSV_ONLY_INT:
            parts.append((f"CAST(NULL AS INTEGER)" if pq_only else f"TRY_CAST({col} AS INTEGER)") + f" AS {col}")
        for col in MS_CSV_ONLY_DBL:
            parts.append((f"CAST(NULL AS DOUBLE)" if pq_only else f"TRY_CAST({col} AS DOUBLE)") + f" AS {col}")
        parts.append((f"CAST(NULL AS TIMESTAMP)" if pq_only else "TRY_CAST(stats_fetched_at AS TIMESTAMP)") + " AS stats_fetched_at")
        return ",\n        ".join(parts)

    con.execute("DROP TABLE IF EXISTS stg_match_stats")
    con.execute(f"""
    CREATE TABLE stg_match_stats AS
    SELECT {sel(False)},
        TRUE AS in_csv,
        (fixture_id IN (SELECT fixture_id FROM raw_ms_pq)) AS in_pq
    FROM raw_ms_csv
    UNION ALL
    SELECT {sel(True)}, FALSE AS in_csv, TRUE AS in_pq
    FROM raw_ms_pq
    WHERE fixture_id NOT IN (SELECT fixture_id FROM raw_ms_csv)
    """)


def build_small(con) -> None:
    # odds: union by fixture_id, prefer CSV
    con.execute("DROP TABLE IF EXISTS stg_odds")
    con.execute("""
    CREATE TABLE stg_odds AS
    SELECT TRY_CAST(fixture_id AS BIGINT) fixture_id, TRY_CAST(home_win AS DOUBLE) home_win,
      TRY_CAST(draw AS DOUBLE) draw, TRY_CAST(away_win AS DOUBLE) away_win,
      CAST(bookmaker AS VARCHAR) bookmaker, CAST("source" AS VARCHAR) AS "source",
      TRUE in_csv, (fixture_id IN (SELECT fixture_id FROM raw_odds_pq)) in_pq
    FROM raw_odds_csv
    UNION ALL
    SELECT TRY_CAST(fixture_id AS BIGINT), TRY_CAST(home_win AS DOUBLE), TRY_CAST(draw AS DOUBLE),
      TRY_CAST(away_win AS DOUBLE), CAST(bookmaker AS VARCHAR), CAST("source" AS VARCHAR), FALSE, TRUE
    FROM raw_odds_pq WHERE fixture_id NOT IN (SELECT fixture_id FROM raw_odds_csv)
    """)

    # lineups: union by (fixture_id, team_id), prefer PQ (richer, has team_name)
    con.execute("DROP TABLE IF EXISTS stg_fixture_lineups")
    con.execute("""
    CREATE TABLE stg_fixture_lineups AS
    SELECT TRY_CAST(fixture_id AS BIGINT) fixture_id, TRY_CAST(team_id AS BIGINT) team_id,
      CAST(team_name AS VARCHAR) team_name, CAST(coach_name AS VARCHAR) coach_name,
      TRY_CAST(coach_api_id AS BIGINT) coach_api_id, CAST(formation AS VARCHAR) formation,
      FALSE in_csv, TRUE in_pq
    FROM raw_lu_pq
    UNION ALL
    SELECT TRY_CAST(c.fixture_id AS BIGINT), TRY_CAST(c.team_id AS BIGINT),
      CAST(NULL AS VARCHAR), CAST(c.coach_name AS VARCHAR), TRY_CAST(c.coach_api_id AS BIGINT),
      CAST(c.formation AS VARCHAR), TRUE, FALSE
    FROM raw_lu_csv c
    WHERE NOT EXISTS (SELECT 1 FROM raw_lu_pq p WHERE p.fixture_id=c.fixture_id AND p.team_id=c.team_id)
    """)

    # teams: union by id, prefer CSV
    con.execute("DROP TABLE IF EXISTS stg_teams")
    con.execute("""
    CREATE TABLE stg_teams AS
    SELECT TRY_CAST(id AS BIGINT) id, CAST("name" AS VARCHAR) AS "name",
      TRY_CAST(api_football_id AS BIGINT) api_football_id, CAST(fd_name AS VARCHAR) fd_name,
      TRY_CAST(rating_mu AS DOUBLE) rating_mu, TRY_CAST(rating_sigma AS DOUBLE) rating_sigma,
      TRUE in_csv, (id IN (SELECT id FROM raw_teams_pq)) in_pq
    FROM raw_teams_csv
    UNION ALL
    SELECT TRY_CAST(id AS BIGINT), CAST("name" AS VARCHAR), TRY_CAST(api_football_id AS BIGINT),
      CAST(fd_name AS VARCHAR), TRY_CAST(rating_mu AS DOUBLE), TRY_CAST(rating_sigma AS DOUBLE),
      FALSE, TRUE
    FROM raw_teams_pq WHERE id NOT IN (SELECT id FROM raw_teams_csv)
    """)

    # players: CSV is a superset (only-in-parquet=0)
    con.execute("DROP TABLE IF EXISTS stg_players")
    con.execute("""
    CREATE TABLE stg_players AS
    SELECT TRY_CAST(id AS BIGINT) id, TRY_CAST(api_football_id AS BIGINT) api_football_id,
      CAST("name" AS VARCHAR) AS "name", CAST(firstname AS VARCHAR) firstname, CAST(lastname AS VARCHAR) lastname,
      TRY_CAST(age AS INTEGER) age, CAST(nationality AS VARCHAR) nationality,
      CAST(height AS VARCHAR) height, CAST(weight AS VARCHAR) weight, CAST(photo AS VARCHAR) photo,
      TRUE in_csv, (id IN (SELECT id FROM raw_players_pq)) in_pq
    FROM raw_players_csv
    """)

    # leagues: CSV holds all 144
    con.execute("DROP TABLE IF EXISTS stg_leagues")
    con.execute("""
    CREATE TABLE stg_leagues AS
    SELECT TRY_CAST(id AS BIGINT) id, CAST("name" AS VARCHAR) AS "name", CAST(country AS VARCHAR) country,
      CAST(fd_code AS VARCHAR) fd_code, TRY_CAST(api_football_id AS BIGINT) api_football_id,
      TRUE in_csv, (id IN (SELECT id FROM raw_leagues_pq)) in_pq
    FROM raw_leagues_csv
    """)

    # player tables are identical across snapshots -> reference parquet directly
    con.execute(f"CREATE OR REPLACE VIEW stg_fixture_players AS SELECT * FROM read_parquet('{PQ}/fixture_players.parquet')")
    con.execute(f"CREATE OR REPLACE VIEW stg_fixture_players_stats_flat AS SELECT * FROM read_parquet('{PQ}/fixture_players_stats_flat.parquet')")


def integrity_report(con) -> dict:
    def scalar(sql: str) -> int:
        return con.execute(sql).fetchone()[0]

    rep: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "counts": {}, "orphans": {}, "checks": {}}
    for t in ["stg_leagues", "stg_teams", "stg_players", "stg_fixtures", "stg_match_stats",
              "stg_odds", "stg_fixture_lineups", "stg_fixture_players", "stg_fixture_players_stats_flat"]:
        rep["counts"][t] = scalar(f"SELECT count(*) FROM {t}")

    O = rep["orphans"]
    O["fixtures.league_id->leagues"] = scalar("SELECT count(*) FROM stg_fixtures f WHERE f.league_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM stg_leagues l WHERE l.id=f.league_id)")
    O["fixtures.home_team->teams"] = scalar("SELECT count(*) FROM stg_fixtures f WHERE f.home_team_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM stg_teams t WHERE t.id=f.home_team_id)")
    O["fixtures.away_team->teams"] = scalar("SELECT count(*) FROM stg_fixtures f WHERE f.away_team_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM stg_teams t WHERE t.id=f.away_team_id)")
    O["match_stats.fixture->fixtures"] = scalar("SELECT count(*) FROM stg_match_stats m WHERE NOT EXISTS(SELECT 1 FROM stg_fixtures f WHERE f.id=m.fixture_id)")
    O["odds.fixture->fixtures"] = scalar("SELECT count(*) FROM stg_odds o WHERE NOT EXISTS(SELECT 1 FROM stg_fixtures f WHERE f.id=o.fixture_id)")
    O["lineups.fixture->fixtures"] = scalar("SELECT count(*) FROM stg_fixture_lineups u WHERE NOT EXISTS(SELECT 1 FROM stg_fixtures f WHERE f.id=u.fixture_id)")
    O["lineups.team->teams"] = scalar("SELECT count(*) FROM stg_fixture_lineups u WHERE u.team_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM stg_teams t WHERE t.id=u.team_id)")
    O["fixture_players.fixture->fixtures"] = scalar("SELECT count(*) FROM stg_fixture_players p WHERE NOT EXISTS(SELECT 1 FROM stg_fixtures f WHERE f.id=p.fixture_id)")
    O["fixture_players.player->players"] = scalar("SELECT count(*) FROM stg_fixture_players p WHERE p.player_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM stg_players pl WHERE pl.id=p.player_id)")
    O["fixture_players.team->teams"] = scalar("SELECT count(*) FROM stg_fixture_players p WHERE p.team_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM stg_teams t WHERE t.id=p.team_id)")
    O["stats_flat.fixture->fixtures"] = scalar("SELECT count(*) FROM stg_fixture_players_stats_flat s WHERE NOT EXISTS(SELECT 1 FROM stg_fixtures f WHERE f.id=s.fixture_id)")
    O["stats_flat.fixture_player->fixture_players"] = scalar("SELECT count(*) FROM stg_fixture_players_stats_flat s WHERE NOT EXISTS(SELECT 1 FROM stg_fixture_players p WHERE p.id=s.fixture_player_id)")

    K = rep["checks"]
    K["fixtures_total"] = scalar("SELECT count(*) FROM stg_fixtures")
    K["fixtures_distinct_id"] = scalar("SELECT count(DISTINCT id) FROM stg_fixtures")
    K["fixtures_in_both"] = scalar("SELECT count(*) FROM stg_fixtures WHERE in_csv AND in_pq")
    K["fixtures_csv_only"] = scalar("SELECT count(*) FROM stg_fixtures WHERE in_csv AND NOT in_pq")
    K["fixtures_pq_only"] = scalar("SELECT count(*) FROM stg_fixtures WHERE in_pq AND NOT in_csv")
    K["fixture_conflicts"] = scalar("SELECT count(*) FROM audit_fixture_conflicts")
    K["match_stats_distinct_fixture"] = scalar("SELECT count(DISTINCT fixture_id) FROM stg_match_stats")
    K["match_stats_rows"] = scalar("SELECT count(*) FROM stg_match_stats")
    K["odds_distinct_fixture"] = scalar("SELECT count(DISTINCT fixture_id) FROM stg_odds")
    K["lineups_distinct_pair"] = scalar("SELECT count(*) FROM (SELECT DISTINCT fixture_id, team_id FROM stg_fixture_lineups)")
    K["biz_key_dupe_fixtures"] = scalar("""
      SELECT COALESCE(SUM(cnt-1),0) FROM (
        SELECT count(*) cnt FROM stg_fixtures
        GROUP BY league_id, date_trunc('day', date_utc), home_team_id, away_team_id
        HAVING count(*) > 1)""")
    return rep


def main() -> None:
    t0 = time.time()
    con = staging.connect()
    load_raw(con)
    _log("building canonical fixtures + conflict audit...")
    build_fixtures(con)
    _log("building canonical match_stats...")
    build_match_stats(con)
    _log("building canonical teams/players/leagues/odds/lineups...")
    build_small(con)
    _log("running integrity report...")
    rep = integrity_report(con)
    (c.QA_OUT_DIR / "phase1_report.json").write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")

    print("\n===== PHASE 1 RECONCILIATION REPORT =====")
    print("counts:")
    for k, v in rep["counts"].items():
        print(f"  {k:<34} {v:>12,}")
    print("checks:")
    for k, v in rep["checks"].items():
        print(f"  {k:<34} {v:>12,}")
    print("orphans (all should be 0):")
    bad = 0
    for k, v in rep["orphans"].items():
        flag = "" if v == 0 else "  <-- NONZERO"
        if v:
            bad += 1
        print(f"  {k:<40} {v:>10,}{flag}")
    con.close()
    print(f"\nnonzero-orphan checks: {bad}")
    print(f"elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
