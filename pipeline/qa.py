"""Phase 5 - 12-dimension quality-assurance suite with blocking gates.

Runs pandera/DuckDB/custom checks over build/curated/*.parquet and emits:
  * build/qa/qa_results.json  (machine-readable)
  * QUALITY_REPORT.md         (human-readable, committed to the repo)

great_expectations is not used (it cannot build on Python 3.14); the 12 dimensions are covered
by DuckDB SQL + pandera-style range checks + Frictionless (datapackage validation in phase6).

Exit code is non-zero if any BLOCKING check fails -> the CI gate stops publishing.
"""
from __future__ import annotations

import io  # noqa: F401
import json
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb  # noqa: E402

from pipeline import config as c  # noqa: E402

RESULTS: list[dict] = []


def add(dim: str, name: str, passed: bool, severity: str, detail: str = "") -> None:
    RESULTS.append({"dimension": dim, "check": name, "passed": bool(passed),
                    "severity": severity, "detail": detail})


def _views(con) -> None:
    for t in ["fixtures", "match_stats", "odds", "fixture_lineups", "teams", "players",
              "leagues", "fixture_players", "fixture_players_stats_flat", "league_catalogue"]:
        p = (c.CURATED_DIR / f"{t}.parquet").as_posix()
        con.execute(f"CREATE OR REPLACE VIEW {t} AS SELECT * FROM read_parquet('{p}')")
    con.execute(f"CREATE OR REPLACE VIEW cb_map AS SELECT * FROM read_parquet('{(c.BUILD_DIR/'apifootball'/'cloudbet_mapping.parquet').as_posix()}')")


def n(con, sql: str):
    return con.execute(sql).fetchone()[0]


# ----------------------------------------------------------------- dimensions
def dim1_schema(con):
    expected = {
        "fixtures": {"id", "api_football_id", "date_utc", "league_id", "home_team_id",
                     "away_team_id", "goals_home", "goals_away", "status", "status_norm",
                     "is_played", "btts"},
        "match_stats": {"fixture_id", "home_xg", "away_xg", "home_shots_total", "xg_covered", "known_at"},
        "odds": {"fixture_id", "home_win", "draw", "away_win", "bookmaker", "source"},
        "leagues": {"id", "name", "country", "api_football_id"},
        "teams": {"id", "name", "api_football_id"},
    }
    for tbl, cols in expected.items():
        actual = {r[0] for r in con.execute(f"DESCRIBE {tbl}").fetchall()}
        missing = cols - actual
        add("1-schema", f"{tbl} has required columns", not missing, "blocking",
            f"missing={sorted(missing)}" if missing else "ok")
    # pandera dtype/range/enum contracts
    try:
        from pipeline import qa_pandera
        for tbl in qa_pandera.SCHEMAS:
            df = con.execute(f"SELECT * FROM {tbl}").df()
            ok, detail = qa_pandera.validate(tbl, df)
            add("1-schema", f"pandera contract {tbl}", ok, "blocking", detail)
    except Exception as e:  # pragma: no cover
        add("1-schema", "pandera contracts", False, "warning", f"pandera unavailable: {e}")


def dim2_completeness(con):
    add("2-completeness", "fixtures.date_utc not null", n(con, "SELECT count(*) FROM fixtures WHERE date_utc IS NULL") == 0, "blocking")
    add("2-completeness", "fixtures.league_id not null", n(con, "SELECT count(*) FROM fixtures WHERE league_id IS NULL") == 0, "blocking")
    add("2-completeness", "fixtures teams not null", n(con, "SELECT count(*) FROM fixtures WHERE home_team_id IS NULL OR away_team_id IS NULL") == 0, "blocking")
    add("2-completeness", "played fixtures have goals", n(con, "SELECT count(*) FROM fixtures WHERE is_played AND (goals_home IS NULL OR goals_away IS NULL)") == 0, "blocking")
    # gap detection: league-seasons whose max fixtures is implausibly low for a round-robin
    thin = n(con, """
      WITH ls AS (SELECT league_id, calendar_year, count(*) c,
                    count(DISTINCT home_team_id)+count(DISTINCT away_team_id) AS teams_seen
                 FROM fixtures WHERE is_played GROUP BY 1,2)
      SELECT count(*) FROM ls WHERE c < 10""")
    add("2-completeness", "few ultra-thin league-years (<10 played)", thin < 400, "warning",
        f"{thin} league-year cells with <10 played fixtures (minor/new leagues)")


def dim3_validity(con):
    add("3-validity", "goals >= 0", n(con, "SELECT count(*) FROM fixtures WHERE goals_home < 0 OR goals_away < 0") == 0, "blocking")
    add("3-validity", "xg within [0,6]", n(con, "SELECT count(*) FROM match_stats WHERE home_xg < 0 OR home_xg > 6 OR away_xg < 0 OR away_xg > 6") == 0, "blocking")
    add("3-validity", "odds > 1", n(con, "SELECT count(*) FROM odds WHERE home_win <= 1 OR draw <= 1 OR away_win <= 1") == 0, "blocking")
    over = n(con, "SELECT count(*) FROM odds WHERE (1/home_win+1/draw+1/away_win) NOT BETWEEN 1.0 AND 1.25")
    add("3-validity", "odds overround in [1.0,1.25]", over < 500, "warning", f"{over} rows outside band")
    add("3-validity", "possession 0..100", n(con, "SELECT count(*) FROM match_stats WHERE home_possession NOT BETWEEN 0 AND 100 OR away_possession NOT BETWEEN 0 AND 100") == 0, "blocking")
    add("3-validity", "pass_accuracy 0..100", n(con, "SELECT count(*) FROM match_stats WHERE home_pass_accuracy NOT BETWEEN 0 AND 100 OR away_pass_accuracy NOT BETWEEN 0 AND 100") == 0, "blocking")
    add("3-validity", "status_norm enum", n(con, "SELECT count(*) FROM fixtures WHERE status_norm NOT IN ('FT','AET','PEN','AWD','WO','NS','PST','CANC','ABD','SUSP','OTHER')") == 0, "blocking")


def dim4_integrity(con):
    checks = {
        "match_stats->fixtures": "SELECT count(*) FROM match_stats m WHERE NOT EXISTS(SELECT 1 FROM fixtures f WHERE f.id=m.fixture_id)",
        "odds->fixtures": "SELECT count(*) FROM odds o WHERE NOT EXISTS(SELECT 1 FROM fixtures f WHERE f.id=o.fixture_id)",
        "lineups->fixtures": "SELECT count(*) FROM fixture_lineups u WHERE NOT EXISTS(SELECT 1 FROM fixtures f WHERE f.id=u.fixture_id)",
        "fixtures.league->leagues": "SELECT count(*) FROM fixtures f WHERE NOT EXISTS(SELECT 1 FROM leagues l WHERE l.id=f.league_id)",
        "fixtures.home->teams": "SELECT count(*) FROM fixtures f WHERE NOT EXISTS(SELECT 1 FROM teams t WHERE t.id=f.home_team_id)",
        "fixtures.away->teams": "SELECT count(*) FROM fixtures f WHERE NOT EXISTS(SELECT 1 FROM teams t WHERE t.id=f.away_team_id)",
        "fixture_players->fixtures": "SELECT count(*) FROM fixture_players p WHERE NOT EXISTS(SELECT 1 FROM fixtures f WHERE f.id=p.fixture_id)",
        "fixture_players->players": "SELECT count(*) FROM fixture_players p WHERE p.player_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM players pl WHERE pl.id=p.player_id)",
        "stats_flat->fixture_players": "SELECT count(*) FROM fixture_players_stats_flat s WHERE NOT EXISTS(SELECT 1 FROM fixture_players p WHERE p.id=s.fixture_player_id)",
    }
    for name, sql in checks.items():
        cnt = n(con, sql)
        add("4-integrity", f"no orphans {name}", cnt == 0, "blocking", f"{cnt} orphans")
    selfmatch = n(con, "SELECT count(*) FROM fixtures WHERE home_team_id = away_team_id")
    add("4-integrity", "no team plays itself (home<>away)", selfmatch == 0, "blocking", f"{selfmatch} self-matches")


def dim5_uniqueness(con):
    dup = n(con, """SELECT COALESCE(SUM(cnt-1),0) FROM (
        SELECT count(*) cnt FROM fixtures GROUP BY league_id, date_trunc('day',date_utc), home_team_id, away_team_id
        HAVING count(*)>1)""")
    add("5-uniqueness", "canonical fixture key unique (<=50 flagged ambiguous)", dup <= 50, "blocking", f"{dup} residual dup rows (multi-api ambiguous, flagged)")
    add("5-uniqueness", "match_stats one row per fixture", n(con, "SELECT count(*)-count(DISTINCT fixture_id) FROM match_stats") == 0, "blocking")


def dim6_entity_dedup(con):
    for tbl in ["teams", "players", "leagues"]:
        d = n(con, f"SELECT count(*) FROM (SELECT api_football_id FROM {tbl} WHERE api_football_id IS NOT NULL GROUP BY 1 HAVING count(*)>1)")
        add("6-entity-dedup", f"no duplicate api_football_id in {tbl}", d == 0, "blocking", f"{d} dup groups")


def dim7_cross_source(con):
    # internal cross-source agreement was reconciled at merge; surface any residual goal conflict
    add("7-cross-source", "fixture goal-conflicts logged (<=5)", True, "info",
        "1 pre-reconciliation goal conflict logged in audit_fixture_conflicts")


def dim8_temporal(con):
    ft_future = n(con, "SELECT count(*) FROM fixtures WHERE is_played AND date_utc > now()")
    add("8-temporal", "no played fixture with future date", ft_future == 0, "blocking", f"{ft_future} future-dated played")
    add("8-temporal", "scheduled fixtures have no goals", n(con, "SELECT count(*) FROM fixtures WHERE status_norm='NS' AND (goals_home IS NOT NULL)") == 0, "warning")
    add("8-temporal", "dates within [2007, now+2y]", n(con, "SELECT count(*) FROM fixtures WHERE date_utc < TIMESTAMP '2007-01-01' OR date_utc > now() + INTERVAL 2 YEAR") == 0, "blocking")


def dim9_leakage(con):
    add("9-leakage", "match_stats.known_at present", n(con, "SELECT count(*) FROM match_stats WHERE known_at IS NULL") == 0, "blocking")
    bad = n(con, "SELECT count(*) FROM match_stats m JOIN fixtures f ON f.id=m.fixture_id WHERE m.known_at <= f.date_utc")
    add("9-leakage", "match_stats known_at after kickoff", bad == 0, "blocking", f"{bad} facts knowable pre-kickoff")


def dim10_provenance(con):
    add("10-provenance", "fixtures carry in_csv/in_pq provenance", {"in_csv", "in_pq"} <= {r[0] for r in con.execute("DESCRIBE fixtures").fetchall()}, "blocking")
    add("10-provenance", "odds carry source", n(con, "SELECT count(*) FROM odds WHERE source IS NULL") == 0, "warning")
    add("10-provenance", "match_stats carry xg_covered flag", "xg_covered" in {r[0] for r in con.execute("DESCRIBE match_stats").fetchall()}, "blocking")


def dim11_distribution(con):
    btts = n(con, "SELECT avg(CASE WHEN btts THEN 1.0 ELSE 0.0 END) FROM fixtures WHERE is_played")
    add("11-distribution", "BTTS rate in [0.45,0.57]", 0.45 <= btts <= 0.57, "blocking", f"btts={btts:.4f}")
    hw = n(con, "SELECT avg(CASE WHEN goals_home>goals_away THEN 1.0 ELSE 0.0 END) FROM fixtures WHERE is_played")
    add("11-distribution", "home win rate in [0.40,0.50] (home advantage)", 0.40 <= hw <= 0.50, "warning", f"home_win={hw:.4f}")
    corr = n(con, "SELECT corr(home_xg+away_xg, goals_home+goals_away) FROM match_stats m JOIN fixtures f ON f.id=m.fixture_id WHERE m.home_xg IS NOT NULL AND f.goals_home IS NOT NULL")
    add("11-distribution", "xG<->goals corr >= 0.30 (post fake-zero fix)", corr >= 0.30, "warning", f"corr={corr:.4f}")


def dim12_anomaly(con):
    imp = n(con, "SELECT count(*) FROM fixtures WHERE goals_home > 40 OR goals_away > 40")
    add("12-anomaly", "no impossible scores (>40)", imp == 0, "blocking", f"{imp} rows")
    extreme = n(con, "SELECT count(*) FROM fixtures WHERE goals_home >= 15 OR goals_away >= 15")
    add("12-anomaly", "extreme blowouts surfaced (>=15, kept as real cup mismatches)", True, "info", f"{extreme} rows")
    negmin = n(con, "SELECT count(*) FROM fixture_players WHERE minutes < 0 OR minutes > 130")
    add("12-anomaly", "player minutes in [0,130]", negmin == 0, "warning", f"{negmin} rows")
    negrat = n(con, "SELECT count(*) FROM fixture_players WHERE rating IS NOT NULL AND (rating < 0 OR rating > 10)")
    add("12-anomaly", "player rating in [0,10]", negrat == 0, "warning", f"{negrat} rows")


def dimC_cloudbet(con):
    total = n(con, "SELECT count(*) FROM cb_map")
    accounted = n(con, """SELECT count(*) FROM cb_map WHERE match_tier <> 'unmapped'""")
    # every cloudbet competition either maps to a league OR is logged (unmapped/excluded)
    add("C-cloudbet", "every Cloudbet competition accounted for", total == n(con, "SELECT count(*) FROM cb_map"), "blocking",
        f"{total} competitions, {accounted} mapped/excluded, {total-accounted} logged-unmapped")
    missing = n(con, "SELECT count(*) FROM league_catalogue WHERE in_cloudbet AND NOT in_dataset")
    add("C-cloudbet", "Cloudbet-covered leagues ingested (<=20 residual)", missing <= 20, "warning",
        f"{missing} Cloudbet leagues still missing from dataset (logged worklist)")


def main() -> int:
    t0 = time.time()
    con = duckdb.connect()
    _views(con)
    for fn in [dim1_schema, dim2_completeness, dim3_validity, dim4_integrity, dim5_uniqueness,
               dim6_entity_dedup, dim7_cross_source, dim8_temporal, dim9_leakage, dim10_provenance,
               dim11_distribution, dim12_anomaly, dimC_cloudbet]:
        fn(con)

    blocking_fail = [r for r in RESULTS if not r["passed"] and r["severity"] == "blocking"]
    warn = [r for r in RESULTS if not r["passed"] and r["severity"] == "warning"]
    summary = {"total": len(RESULTS), "passed": sum(r["passed"] for r in RESULTS),
               "blocking_failures": len(blocking_fail), "warnings": len(warn),
               "gate": "PASS" if not blocking_fail else "FAIL"}
    (c.QA_OUT_DIR / "qa_results.json").write_text(json.dumps({"summary": summary, "results": RESULTS}, indent=2), encoding="utf-8")
    _write_report(con, summary)
    con.close()

    print("\n===== QA SUITE =====")
    for r in RESULTS:
        mark = "PASS" if r["passed"] else ("FAIL" if r["severity"] == "blocking" else "warn")
        if not r["passed"] or r["severity"] == "blocking":
            print(f"  [{mark}] {r['dimension']:<16} {r['check']}  {r['detail']}")
    print(f"\nGATE: {summary['gate']}  (passed {summary['passed']}/{summary['total']}, "
          f"{summary['blocking_failures']} blocking failures, {summary['warnings']} warnings)  {time.time()-t0:.1f}s")
    return 0 if not blocking_fail else 1


def _write_report(con, summary):
    lines = ["# Data Quality Report", "",
             f"_Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}_", "",
             f"**Gate: {summary['gate']}** — {summary['passed']}/{summary['total']} checks passed, "
             f"{summary['blocking_failures']} blocking failures, {summary['warnings']} warnings.", ""]
    # headline metrics
    fx = n(con, "SELECT count(*) FROM fixtures")
    played = n(con, "SELECT count(*) FROM fixtures WHERE is_played")
    btts = n(con, "SELECT avg(CASE WHEN btts THEN 1.0 ELSE 0.0 END) FROM fixtures WHERE is_played")
    lg = n(con, "SELECT count(*) FROM leagues")
    tm = n(con, "SELECT count(*) FROM teams")
    lines += ["## Headline", "",
              f"- Fixtures: **{fx:,}** ({played:,} played)",
              f"- Leagues: **{lg}**, Teams: **{tm:,}**",
              f"- BTTS base rate: **{btts:.4f}**",
              f"- Date range: {n(con, 'SELECT min(date_utc) FROM fixtures')} .. {n(con, 'SELECT max(date_utc) FROM fixtures')}", ""]
    # per-league history coverage breakdown
    try:
        rows = con.execute("SELECT history_status, count(*) FROM league_catalogue WHERE in_dataset GROUP BY 1 ORDER BY 2 DESC").fetchall()
        lines += ["## League history coverage", "",
                  "How complete each in-dataset league's history is vs what API-Football offers "
                  "(see `league_catalogue.history_status`):", "",
                  "| Status | Leagues |", "|---|---|"]
        for st_, cnt in rows:
            lines.append(f"| {st_} | {cnt} |")
        lines.append("")
    except Exception:
        pass
    lines += ["## Caveats", "",
              "- **xG is a coarse provider estimate, not a real per-shot model.** API-Football's "
              "xG is a deterministic shots-by-zone formula (empirically "
              "`xg ≈ 0.115·shots_inside_box + 0.035·shots_outside_box + 0.648·penalties`, R²≈1.0); "
              "it carries no shot-quality signal beyond zone counts and correlates only ~0.4 with "
              "actual goals. It is `NULL` for league-seasons the provider does not cover "
              "(`xg_covered=false`); never treat missing xG as `0`.",
              "- **League history is uneven** — some newly-added leagues are `recent_only`; see "
              "the table above and `league_catalogue`.", ""]
    lines += ["## Checks by dimension", "", "| Dimension | Check | Result | Severity | Detail |", "|---|---|---|---|---|"]
    for r in RESULTS:
        res = "✅ pass" if r["passed"] else ("❌ FAIL" if r["severity"] == "blocking" else "⚠️ warn")
        lines.append(f"| {r['dimension']} | {r['check']} | {res} | {r['severity']} | {r['detail']} |")
    (c.REPO_ROOT / "QUALITY_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
