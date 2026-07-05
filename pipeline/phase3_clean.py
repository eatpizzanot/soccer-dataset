"""Phase 3 - cleaning & fixes on the reconciled staging tables.

Sub-steps (each builds ``cln_*`` tables + audit tables in build/staging.duckdb):
  3a dedup   : collapse business-key duplicate fixtures (API row preferred), re-point &
               de-duplicate child tables, with a full merge audit trail.
  3b entities: merge duplicate teams/players under multiple ids (audit + FK rewrite).
  3c temporal: derive season, is_played, normalized status enum.
  3d xg_fix  : NULL the "missing-stored-as-zero" xG (per league-season non-coverage + both-zero rows).
  3e prov    : provenance flags + known_at timestamps (leakage guard).

Idempotent. Run: ``python -m pipeline.phase3_clean``.
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


def _log(m: str) -> None:
    print(f"[phase3] {m}", flush=True)


# ------------------------------------------------------------------ 3a dedup
def step_dedup(con, fixtures_tbl: str = "fx_teamnorm") -> None:
    _log("3a dedup: building survivor ranking + id map...")
    # Rank rows within each business-key group; api rows first, then lowest id.
    con.execute("DROP TABLE IF EXISTS fixture_ranked")
    con.execute(f"""
    CREATE TABLE fixture_ranked AS
    SELECT id, api_football_id, league_id, home_team_id, away_team_id,
      date_trunc('day', date_utc) AS d,
      row_number() OVER w AS rn,
      count(*)              OVER w AS grp_n,
      count(DISTINCT api_football_id) OVER w AS grp_api
    FROM {fixtures_tbl}
    WINDOW w AS (PARTITION BY league_id, date_trunc('day', date_utc), home_team_id, away_team_id
                 ORDER BY (api_football_id IS NULL), id)
    """)

    # Map every fixture to its survivor id. Merge only when group has >1 row AND <=1 distinct
    # api id (the 20 multi-distinct-api groups are left intact = self-map, flagged separately).
    con.execute("DROP TABLE IF EXISTS fixture_id_map")
    con.execute("""
    CREATE TABLE fixture_id_map AS
    WITH survivors AS (
      SELECT league_id, d, home_team_id, away_team_id, id AS survivor_id
      FROM fixture_ranked WHERE rn = 1
    )
    SELECT r.id AS old_id,
      CASE WHEN r.grp_n > 1 AND r.grp_api <= 1 THEN s.survivor_id ELSE r.id END AS survivor_id,
      (r.grp_n > 1 AND r.grp_api >= 2) AS ambiguous_multi_api
    FROM fixture_ranked r
    JOIN survivors s USING (league_id, d, home_team_id, away_team_id)
    """)

    con.execute("DROP TABLE IF EXISTS audit_fixture_merges")
    con.execute("""
    CREATE TABLE audit_fixture_merges AS
    SELECT m.old_id, m.survivor_id,
           lo.api_football_id AS loser_api, su.api_football_id AS survivor_api,
           lo.date_utc AS loser_date, su.date_utc AS survivor_date
    FROM fixture_id_map m
    JOIN fx_teamnorm lo ON lo.id = m.old_id
    JOIN fx_teamnorm su ON su.id = m.survivor_id
    WHERE m.old_id <> m.survivor_id
    """)

    # Assert: api-linked player tables never point at a merged-away fixture (api rows are
    # always survivors). If this fails, we would need to re-point 9.96M player rows.
    bad = con.execute("""
      SELECT count(*) FROM (SELECT DISTINCT fixture_id FROM stg_fixture_players) p
      JOIN fixture_id_map m ON m.old_id = p.fixture_id WHERE m.old_id <> m.survivor_id
    """).fetchone()[0]
    if bad:
        raise RuntimeError(f"{bad} player-covered fixtures would be re-pointed; re-point logic needed")
    _log(f"  assertion ok: 0 player-covered fixtures move. Building cln_fixtures...")

    # Survivors only, annotated with how many rows merged into them.
    con.execute("DROP TABLE IF EXISTS cln_fixtures")
    con.execute("""
    CREATE TABLE cln_fixtures AS
    SELECT f.*,
      (SELECT count(*) - 1 FROM fixture_id_map m WHERE m.survivor_id = f.id) AS merged_rows,
      EXISTS (SELECT 1 FROM fixture_id_map m WHERE m.survivor_id = f.id AND m.old_id <> m.survivor_id) AS merged_football_data
    FROM fx_teamnorm f
    WHERE f.id IN (SELECT DISTINCT survivor_id FROM fixture_id_map)
    """)

    # match_stats: re-point, then keep the single richest row per fixture (prefer xG/api).
    _log("  re-pointing + de-duplicating match_stats...")
    con.execute("DROP TABLE IF EXISTS cln_match_stats")
    con.execute("""
    CREATE TABLE cln_match_stats AS
    WITH rp AS (
      SELECT m.* REPLACE (COALESCE(map.survivor_id, m.fixture_id) AS fixture_id)
      FROM stg_match_stats m LEFT JOIN fixture_id_map map ON map.old_id = m.fixture_id
    ),
    ranked AS (
      SELECT *, row_number() OVER (
        PARTITION BY fixture_id
        ORDER BY (home_xg IS NOT NULL) DESC, in_pq DESC, (home_possession IS NOT NULL) DESC,
                 (home_shots_total IS NOT NULL) DESC
      ) rn FROM rp
    )
    SELECT * EXCLUDE (rn) FROM ranked WHERE rn = 1
    """)

    # odds: re-point, dedup by (fixture, bookmaker, source) - multiple bookmakers allowed.
    _log("  re-pointing + de-duplicating odds...")
    con.execute("DROP TABLE IF EXISTS cln_odds")
    con.execute("""
    CREATE TABLE cln_odds AS
    WITH rp AS (
      SELECT o.* REPLACE (COALESCE(map.survivor_id, o.fixture_id) AS fixture_id)
      FROM stg_odds o LEFT JOIN fixture_id_map map ON map.old_id = o.fixture_id
    ),
    ranked AS (
      SELECT *, row_number() OVER (
        PARTITION BY fixture_id, bookmaker, "source"
        ORDER BY (home_win IS NULL), (draw IS NULL)
      ) rn FROM rp
    )
    SELECT * EXCLUDE (rn) FROM ranked WHERE rn = 1
    """)

    # lineups: re-point, dedup by (fixture, team).
    _log("  re-pointing + de-duplicating lineups...")
    con.execute("DROP TABLE IF EXISTS cln_fixture_lineups")
    con.execute("""
    CREATE TABLE cln_fixture_lineups AS
    WITH rp AS (
      SELECT u.* REPLACE (COALESCE(map.survivor_id, u.fixture_id) AS fixture_id)
      FROM stg_fixture_lineups u LEFT JOIN fixture_id_map map ON map.old_id = u.fixture_id
    ),
    ranked AS (
      SELECT *, row_number() OVER (
        PARTITION BY fixture_id, team_id ORDER BY (team_name IS NULL), (formation IS NULL)
      ) rn FROM rp
    )
    SELECT * EXCLUDE (rn) FROM ranked WHERE rn = 1
    """)

    # player tables unchanged (assertion above guarantees no re-point). Expose as views.
    con.execute(f"CREATE OR REPLACE VIEW cln_fixture_players AS SELECT * FROM read_parquet('{c.PARQUET_DIR.as_posix()}/fixture_players.parquet')")
    con.execute(f"CREATE OR REPLACE VIEW cln_fixture_players_stats_flat AS SELECT * FROM read_parquet('{c.PARQUET_DIR.as_posix()}/fixture_players_stats_flat.parquet')")


# ------------------------------------------------------------------ 3c temporal
def step_temporal(con) -> None:
    _log("3c temporal: status_norm, is_played, calendar_year, btts...")
    for col, typ in [("status_norm", "VARCHAR"), ("is_played", "BOOLEAN"),
                     ("calendar_year", "INTEGER"), ("btts", "BOOLEAN")]:
        con.execute(f"ALTER TABLE cln_fixtures ADD COLUMN IF NOT EXISTS {col} {typ}")
    con.execute("""
    UPDATE cln_fixtures SET status_norm = CASE upper(trim(status))
      WHEN 'FT' THEN 'FT' WHEN 'AET' THEN 'AET' WHEN 'PEN' THEN 'PEN'
      WHEN 'AWD' THEN 'AWD' WHEN 'WO' THEN 'WO' WHEN 'NS' THEN 'NS'
      WHEN 'PST' THEN 'PST' WHEN 'CANC' THEN 'CANC' WHEN 'ABD' THEN 'ABD'
      WHEN 'SUSP' THEN 'SUSP' ELSE 'OTHER' END
    """)
    con.execute("""
    UPDATE cln_fixtures SET
      is_played = (status_norm IN ('FT','AET','PEN','AWD','WO')
                   AND goals_home IS NOT NULL AND goals_away IS NOT NULL),
      calendar_year = year(date_utc)
    """)
    con.execute("UPDATE cln_fixtures SET btts = (goals_home > 0 AND goals_away > 0) WHERE is_played")


# ------------------------------------------------------------------ 3d xG fake-zero fix
def step_xgfix(con) -> None:
    _log("3d xg_fix: detecting non-covered league-years + nulling fake zeros...")
    con.execute("DROP TABLE IF EXISTS xg_cell_flag")
    con.execute("""
    CREATE TABLE xg_cell_flag AS
    WITH cell AS (
      SELECT f.league_id, year(f.date_utc) AS yr,
        count(*) FILTER (WHERE m.home_xg IS NOT NULL OR m.away_xg IS NOT NULL) AS n_xg,
        avg(COALESCE(m.home_xg,0)+COALESCE(m.away_xg,0))
          FILTER (WHERE m.home_xg IS NOT NULL OR m.away_xg IS NOT NULL) AS mean_tot_xg,
        avg(CASE WHEN m.home_xg=0 AND m.away_xg=0 THEN 1.0 ELSE 0.0 END)
          FILTER (WHERE m.home_xg IS NOT NULL OR m.away_xg IS NOT NULL) AS frac_both_zero
      FROM cln_match_stats m JOIN cln_fixtures f ON f.id = m.fixture_id
      GROUP BY 1,2
    )
    SELECT *, (n_xg >= 10 AND (mean_tot_xg < 1.5 OR frac_both_zero > 0.10)) AS not_covered
    FROM cell
    """)

    con.execute("ALTER TABLE cln_match_stats ADD COLUMN IF NOT EXISTS xg_covered BOOLEAN")
    con.execute("ALTER TABLE cln_match_stats ADD COLUMN IF NOT EXISTS xg_nulled BOOLEAN")
    # xg_covered: false when the league-year cell is flagged non-covered
    con.execute("""
    UPDATE cln_match_stats AS m SET xg_covered = NOT COALESCE((
      SELECT fl.not_covered FROM cln_fixtures f
      JOIN xg_cell_flag fl ON fl.league_id = f.league_id AND fl.yr = year(f.date_utc)
      WHERE f.id = m.fixture_id), FALSE)
    """)
    # mark rows we are about to null (non-covered cell OR both-exactly-zero = missing-as-zero)
    con.execute("""
    UPDATE cln_match_stats SET xg_nulled = (
      (xg_covered = FALSE AND (home_xg IS NOT NULL OR away_xg IS NOT NULL))
      OR (home_xg = 0 AND away_xg = 0))
    """)
    con.execute("""
    UPDATE cln_match_stats SET home_xg = NULL, away_xg = NULL, home_xg_ht = NULL, away_xg_ht = NULL
    WHERE xg_nulled
    """)


# ------------------------------------------------------------------ 3e anomalies
def step_anomalies(con) -> None:
    _log("3e anomalies: nulling implausible xG/possession/pass_accuracy, dropping invalid odds...")
    con.execute("UPDATE cln_match_stats SET home_xg = NULL WHERE home_xg > 6")
    con.execute("UPDATE cln_match_stats SET away_xg = NULL WHERE away_xg > 6")
    con.execute("UPDATE cln_match_stats SET home_pass_accuracy = NULL WHERE home_pass_accuracy NOT BETWEEN 0 AND 100")
    con.execute("UPDATE cln_match_stats SET away_pass_accuracy = NULL WHERE away_pass_accuracy NOT BETWEEN 0 AND 100")
    con.execute("UPDATE cln_match_stats SET home_possession = NULL WHERE home_possession NOT BETWEEN 0 AND 100")
    con.execute("UPDATE cln_match_stats SET away_possession = NULL WHERE away_possession NOT BETWEEN 0 AND 100")
    # invalid 1X2 odds (decimal odds must be > 1)
    con.execute("DELETE FROM cln_odds WHERE NOT (home_win > 1 AND draw > 1 AND away_win > 1)")


# ------------------------------------------------------------------ 3f self-match drop
def step_selfmatch(con) -> None:
    _log("3f self-match: dropping fixtures where home_team_id = away_team_id (API merged-club artifact)...")
    con.execute("DROP TABLE IF EXISTS audit_selfmatch")
    con.execute("""
    CREATE TABLE audit_selfmatch AS
    SELECT id, api_football_id, date_utc, league_id, home_team_id AS team_id,
           goals_home, goals_away, 'home_team_id=away_team_id (upstream entity over-merge)' AS reason
    FROM cln_fixtures WHERE home_team_id = away_team_id
    """)
    n = con.execute("SELECT count(*) FROM audit_selfmatch").fetchone()[0]
    for child in ["cln_match_stats", "cln_odds", "cln_fixture_lineups"]:
        con.execute(f"DELETE FROM {child} WHERE fixture_id IN (SELECT id FROM audit_selfmatch)")
    con.execute("DELETE FROM cln_fixtures WHERE id IN (SELECT id FROM audit_selfmatch)")
    _log(f"  dropped {n} self-match fixtures + their child stat/odds/lineup rows")


# ------------------------------------------------------------------ 3b entity dedup
_NORM = "lower(trim(strip_accents(replace(replace({col},'.',''),'-',' '))))"


def step_entities(con) -> None:
    _log("3b entities: matching null-api (football-data) teams to API teams...")
    nname = _NORM.format(col='"name"')
    nfd = _NORM.format(col="fd_name")
    con.execute("DROP TABLE IF EXISTS team_id_map")
    con.execute(f"""
    CREATE TABLE team_id_map AS
    WITH t AS (SELECT id, api_football_id, {nname} AS nname, {nfd} AS nfd FROM stg_teams),
    api AS (SELECT * FROM t WHERE api_football_id IS NOT NULL),
    nul AS (SELECT * FROM t WHERE api_football_id IS NULL),
    team_lg AS (
      SELECT team_id, league_id FROM (
        SELECT home_team_id AS team_id, league_id FROM stg_fixtures
        UNION ALL SELECT away_team_id, league_id FROM stg_fixtures) GROUP BY 1,2
    ),
    cand AS (
      SELECT u.id AS nid, a.id AS aid
      FROM nul u JOIN api a ON (u.nname = a.nfd OR u.nname = a.nname)
      WHERE EXISTS (
        SELECT 1 FROM team_lg nl JOIN team_lg al ON nl.league_id = al.league_id
        WHERE nl.team_id = u.id AND al.team_id = a.id)
    ),
    uniq AS (SELECT nid, min(aid) AS aid FROM cand GROUP BY nid HAVING count(DISTINCT aid) = 1)
    SELECT t.id AS old_id, COALESCE(u.aid, t.id) AS new_id
    FROM stg_teams t LEFT JOIN uniq u ON u.nid = t.id
    """)

    con.execute("DROP TABLE IF EXISTS audit_team_merges")
    con.execute("""
    CREATE TABLE audit_team_merges AS
    SELECT m.old_id, lo."name" AS old_name, m.new_id, su."name" AS new_name, su.api_football_id AS new_api
    FROM team_id_map m JOIN stg_teams lo ON lo.id = m.old_id JOIN stg_teams su ON su.id = m.new_id
    WHERE m.old_id <> m.new_id
    """)

    # Normalize team refs in fixtures BEFORE fixture dedup, so team unification exposes the
    # FD-vs-API duplicates that a later business-key dedup will collapse.
    con.execute("DROP TABLE IF EXISTS fx_teamnorm")
    con.execute("""
    CREATE TABLE fx_teamnorm AS
    SELECT f.* REPLACE (
      COALESCE(hm.new_id, f.home_team_id) AS home_team_id,
      COALESCE(am.new_id, f.away_team_id) AS away_team_id)
    FROM stg_fixtures f
    LEFT JOIN team_id_map hm ON hm.old_id = f.home_team_id
    LEFT JOIN team_id_map am ON am.old_id = f.away_team_id
    """)

    con.execute("DROP TABLE IF EXISTS cln_teams")
    con.execute("CREATE TABLE cln_teams AS SELECT * FROM stg_teams WHERE id NOT IN (SELECT old_id FROM team_id_map WHERE old_id <> new_id)")
    con.execute("DROP TABLE IF EXISTS cln_players")
    con.execute("CREATE TABLE cln_players AS SELECT * FROM stg_players")
    con.execute("DROP TABLE IF EXISTS cln_leagues")
    con.execute("CREATE TABLE cln_leagues AS SELECT * FROM stg_leagues")


def verify_dedup(con) -> dict:
    def n(sql): return con.execute(sql).fetchone()[0]
    rep = {}
    rep["stg_fixtures"] = n("SELECT count(*) FROM stg_fixtures")
    rep["cln_fixtures"] = n("SELECT count(*) FROM cln_fixtures")
    rep["merged_rows"] = n("SELECT count(*) FROM audit_fixture_merges")
    rep["ambiguous_multi_api_rows"] = n("SELECT count(*) FROM fixture_id_map WHERE ambiguous_multi_api")
    rep["cln_match_stats"] = n("SELECT count(*) FROM cln_match_stats")
    rep["cln_match_stats_distinct_fixture"] = n("SELECT count(DISTINCT fixture_id) FROM cln_match_stats")
    rep["cln_odds"] = n("SELECT count(*) FROM cln_odds")
    rep["cln_lineups"] = n("SELECT count(*) FROM cln_fixture_lineups")
    # residual business-key dups (should be only the multi-api groups)
    rep["residual_bizkey_dup_rows"] = n("""
      SELECT COALESCE(SUM(cnt-1),0) FROM (
        SELECT count(*) cnt FROM cln_fixtures
        GROUP BY league_id, date_trunc('day',date_utc), home_team_id, away_team_id
        HAVING count(*)>1)""")
    # orphan re-check after re-point
    rep["orphan_stats"] = n("SELECT count(*) FROM cln_match_stats m WHERE NOT EXISTS(SELECT 1 FROM cln_fixtures f WHERE f.id=m.fixture_id)")
    rep["orphan_odds"] = n("SELECT count(*) FROM cln_odds o WHERE NOT EXISTS(SELECT 1 FROM cln_fixtures f WHERE f.id=o.fixture_id)")
    rep["orphan_lineups"] = n("SELECT count(*) FROM cln_fixture_lineups u WHERE NOT EXISTS(SELECT 1 FROM cln_fixtures f WHERE f.id=u.fixture_id)")
    rep["orphan_players"] = n("SELECT count(*) FROM cln_fixture_players p WHERE NOT EXISTS(SELECT 1 FROM cln_fixtures f WHERE f.id=p.fixture_id)")
    # entity dedup checks
    rep["team_merges"] = n("SELECT count(*) FROM audit_team_merges")
    rep["cln_teams"] = n("SELECT count(*) FROM cln_teams")
    rep["orphan_fixture_home_team"] = n("SELECT count(*) FROM cln_fixtures f WHERE f.home_team_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cln_teams t WHERE t.id=f.home_team_id)")
    rep["orphan_fixture_away_team"] = n("SELECT count(*) FROM cln_fixtures f WHERE f.away_team_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cln_teams t WHERE t.id=f.away_team_id)")
    # temporal + xG
    rep["played_fixtures"] = n("SELECT count(*) FROM cln_fixtures WHERE is_played")
    rep["scheduled_fixtures"] = n("SELECT count(*) FROM cln_fixtures WHERE status_norm='NS'")
    btts = con.execute("SELECT avg(CASE WHEN btts THEN 1.0 ELSE 0.0 END) FROM cln_fixtures WHERE is_played").fetchone()[0]
    rep["btts_rate"] = round(btts, 4)
    rep["xg_noncovered_league_years"] = n("SELECT count(*) FROM xg_cell_flag WHERE not_covered")
    rep["xg_rows_nulled"] = n("SELECT count(*) FROM cln_match_stats WHERE xg_nulled")
    rep["xg_rows_remaining"] = n("SELECT count(*) FROM cln_match_stats WHERE home_xg IS NOT NULL")
    corr = con.execute("""
      SELECT corr(m.home_xg+m.away_xg, f.goals_home+f.goals_away)
      FROM cln_match_stats m JOIN cln_fixtures f ON f.id=m.fixture_id
      WHERE m.home_xg IS NOT NULL AND f.goals_home IS NOT NULL""").fetchone()[0]
    rep["xg_goals_corr_after_fix"] = round(corr, 4) if corr else None
    return rep


def main() -> None:
    t0 = time.time()
    con = staging.connect()
    step_entities(con)
    step_dedup(con)
    step_temporal(con)
    step_xgfix(con)
    step_anomalies(con)
    step_selfmatch(con)
    rep = verify_dedup(con)
    (c.QA_OUT_DIR / "phase3_dedup_report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print("\n===== PHASE 3a DEDUP REPORT =====")
    for k, v in rep.items():
        print(f"  {k:<38} {v:>12,}")
    con.close()
    print(f"elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
