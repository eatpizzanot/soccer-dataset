"""Phase 4c - integrate ingested fixtures/teams/leagues into the staging tables.

Runs AFTER phase1 (which rebuilds stg_* from files) and BEFORE phase3 (clean). Idempotent:
  * refresh   - overwrite goals/status/date of existing fixtures matched by api_football_id
                (brings results up to the present);
  * new leagues/teams/fixtures get synthetic internal ids (offset 100M, no collision) and are
    appended to stg_*; phase3 then dedups + cleans the combined set.
"""
from __future__ import annotations

import io
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pipeline import config as c  # noqa: E402
from pipeline import staging  # noqa: E402

OFF = 100_000_000


def integrate(con) -> dict:
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "raw_ingest_fixtures" not in have:
        return {"integrated": False, "reason": "no raw_ingest_fixtures"}

    before = con.execute("SELECT count(*) FROM stg_fixtures").fetchone()[0]

    # 1) refresh existing fixtures (fresher results/status/date) matched by api id
    refreshed = con.execute("""
      SELECT count(*) FROM stg_fixtures f
      JOIN raw_ingest_fixtures r ON f.api_football_id = r.api_football_id
    """).fetchone()[0]
    con.execute("""
      UPDATE stg_fixtures SET goals_home = r.goals_home, goals_away = r.goals_away,
        status = r.status, date_utc = r.date_utc, updated_at = now()
      FROM raw_ingest_fixtures r WHERE stg_fixtures.api_football_id = r.api_football_id
    """)

    # 2) new leagues
    con.execute(f"""
      INSERT INTO stg_leagues (id, "name", country, fd_code, api_football_id, in_csv, in_pq)
      SELECT {OFF} + league_af_id, any_value(league_name), any_value(country), NULL, league_af_id, FALSE, FALSE
      FROM raw_ingest_fixtures
      WHERE league_af_id NOT IN (SELECT api_football_id FROM stg_leagues WHERE api_football_id IS NOT NULL)
      GROUP BY league_af_id
    """)

    # 3) new teams
    con.execute(f"""
      INSERT INTO stg_teams (id, "name", api_football_id, fd_name, rating_mu, rating_sigma, in_csv, in_pq)
      SELECT {OFF} + api_football_id, any_value(name), api_football_id, NULL, 1500.0, NULL, FALSE, FALSE
      FROM raw_ingest_teams
      WHERE api_football_id NOT IN (SELECT api_football_id FROM stg_teams WHERE api_football_id IS NOT NULL)
      GROUP BY api_football_id
    """)

    # 4) new fixtures (resolve league/team internal ids; synthetic id for the rest)
    con.execute(f"""
      INSERT INTO stg_fixtures (id, api_football_id, date_utc, league_id, home_team_id, away_team_id,
        goals_home, goals_away, status, referee_name, referee_api_id, created_at, updated_at, in_csv, in_pq)
      SELECT {OFF} + r.api_football_id, r.api_football_id, r.date_utc,
        COALESCE(l.id, {OFF} + r.league_af_id),
        COALESCE(th.id, {OFF} + r.home_team_af_id),
        COALESCE(ta.id, {OFF} + r.away_team_af_id),
        r.goals_home, r.goals_away, r.status, r.referee_name, NULL, now(), now(), FALSE, FALSE
      FROM raw_ingest_fixtures r
      LEFT JOIN stg_leagues l ON l.api_football_id = r.league_af_id
      LEFT JOIN stg_teams th ON th.api_football_id = r.home_team_af_id
      LEFT JOIN stg_teams ta ON ta.api_football_id = r.away_team_af_id
      WHERE r.api_football_id NOT IN (SELECT api_football_id FROM stg_fixtures WHERE api_football_id IS NOT NULL)
    """)

    # 5) ingested match_stats -> stg_match_stats (fill gaps; resolve internal fixture id by api id)
    ms_added = 0
    if "raw_ingest_match_stats" in have:
        before_ms = con.execute("SELECT count(*) FROM stg_match_stats").fetchone()[0]
        con.execute("""
          INSERT INTO stg_match_stats (fixture_id, home_shots_total, away_shots_total,
            home_shots_on_goal, away_shots_on_goal, home_shots_inside_box, away_shots_inside_box,
            home_shots_outside_box, away_shots_outside_box, home_blocked_shots, away_blocked_shots,
            home_penalties, away_penalties, home_corners, away_corners, home_yellow_cards,
            away_yellow_cards, home_red_cards, away_red_cards, home_xg, away_xg, home_possession,
            away_possession, home_fouls, away_fouls, home_offsides, away_offsides, home_pass_accuracy,
            away_pass_accuracy, home_goals_ht, away_goals_ht, home_xg_ht, away_xg_ht, stats_fetched_at,
            in_csv, in_pq)
          SELECT f.id, r.home_shots_total, r.away_shots_total, r.home_shots_on_goal, r.away_shots_on_goal,
            r.home_shots_inside_box, r.away_shots_inside_box, r.home_shots_outside_box, r.away_shots_outside_box,
            r.home_blocked_shots, r.away_blocked_shots, NULL, NULL, r.home_corners, r.away_corners,
            r.home_yellow_cards, r.away_yellow_cards, r.home_red_cards, r.away_red_cards, r.home_xg, r.away_xg,
            r.home_possession, r.away_possession, r.home_fouls, r.away_fouls, r.home_offsides, r.away_offsides,
            r.home_pass_accuracy, r.away_pass_accuracy, rf.ht_home, rf.ht_away, NULL, NULL,
            r.stats_fetched_at, FALSE, FALSE
          FROM raw_ingest_match_stats r
          JOIN stg_fixtures f ON f.api_football_id = r.api_football_id
          JOIN raw_ingest_fixtures rf ON rf.api_football_id = r.api_football_id
          WHERE f.id NOT IN (SELECT fixture_id FROM stg_match_stats)
        """)
        ms_added = con.execute("SELECT count(*) FROM stg_match_stats").fetchone()[0] - before_ms

    # 6) ingested lineups -> stg_fixture_lineups (resolve internal team id by api id)
    lu_added = 0
    if "raw_ingest_lineups" in have:
        before_lu = con.execute("SELECT count(*) FROM stg_fixture_lineups").fetchone()[0]
        con.execute("""
          INSERT INTO stg_fixture_lineups (fixture_id, team_id, team_name, coach_name, coach_api_id, formation, in_csv, in_pq)
          SELECT f.id, t.id, r.team_name, r.coach_name, r.coach_api_id, r.formation, FALSE, FALSE
          FROM raw_ingest_lineups r
          JOIN stg_fixtures f ON f.api_football_id = r.api_football_id
          JOIN stg_teams t ON t.api_football_id = r.team_af_id
          WHERE NOT EXISTS (SELECT 1 FROM stg_fixture_lineups u WHERE u.fixture_id = f.id AND u.team_id = t.id)
        """)
        lu_added = con.execute("SELECT count(*) FROM stg_fixture_lineups").fetchone()[0] - before_lu

    after = con.execute("SELECT count(*) FROM stg_fixtures").fetchone()[0]
    return {"integrated": True, "fixtures_before": before, "fixtures_after": after,
            "new_fixtures": after - before, "refreshed_fixtures": refreshed,
            "match_stats_added": ms_added, "lineups_added": lu_added}


def main() -> None:
    import json
    con = staging.connect()
    rep = integrate(con)
    con.close()
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
