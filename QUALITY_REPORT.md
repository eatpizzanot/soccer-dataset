# Data Quality Report

_Generated 2026-07-04 20:46 UTC_

**Gate: PASS** — 52/52 checks passed, 0 blocking failures, 0 warnings.

## Headline

- Fixtures: **442,721** (424,554 played)
- Leagues: **271**, Teams: **8,810**
- BTTS base rate: **0.5123**
- Date range: 2012-02-04 01:00:00 .. 2027-06-06 15:00:00

## Checks by dimension

| Dimension | Check | Result | Severity | Detail |
|---|---|---|---|---|
| 1-schema | fixtures has required columns | ✅ pass | blocking | ok |
| 1-schema | match_stats has required columns | ✅ pass | blocking | ok |
| 1-schema | odds has required columns | ✅ pass | blocking | ok |
| 1-schema | leagues has required columns | ✅ pass | blocking | ok |
| 1-schema | teams has required columns | ✅ pass | blocking | ok |
| 1-schema | pandera contract fixtures | ✅ pass | blocking | ok |
| 1-schema | pandera contract match_stats | ✅ pass | blocking | ok |
| 1-schema | pandera contract odds | ✅ pass | blocking | ok |
| 1-schema | pandera contract leagues | ✅ pass | blocking | ok |
| 2-completeness | fixtures.date_utc not null | ✅ pass | blocking |  |
| 2-completeness | fixtures.league_id not null | ✅ pass | blocking |  |
| 2-completeness | fixtures teams not null | ✅ pass | blocking |  |
| 2-completeness | played fixtures have goals | ✅ pass | blocking |  |
| 2-completeness | few ultra-thin league-years (<10 played) | ✅ pass | warning | 95 league-year cells with <10 played fixtures (minor/new leagues) |
| 3-validity | goals >= 0 | ✅ pass | blocking |  |
| 3-validity | xg within [0,6] | ✅ pass | blocking |  |
| 3-validity | odds > 1 | ✅ pass | blocking |  |
| 3-validity | odds overround in [1.0,1.25] | ✅ pass | warning | 364 rows outside band |
| 3-validity | possession 0..100 | ✅ pass | blocking |  |
| 3-validity | pass_accuracy 0..100 | ✅ pass | blocking |  |
| 3-validity | status_norm enum | ✅ pass | blocking |  |
| 4-integrity | no orphans match_stats->fixtures | ✅ pass | blocking | 0 orphans |
| 4-integrity | no orphans odds->fixtures | ✅ pass | blocking | 0 orphans |
| 4-integrity | no orphans lineups->fixtures | ✅ pass | blocking | 0 orphans |
| 4-integrity | no orphans fixtures.league->leagues | ✅ pass | blocking | 0 orphans |
| 4-integrity | no orphans fixtures.home->teams | ✅ pass | blocking | 0 orphans |
| 4-integrity | no orphans fixtures.away->teams | ✅ pass | blocking | 0 orphans |
| 4-integrity | no orphans fixture_players->fixtures | ✅ pass | blocking | 0 orphans |
| 4-integrity | no orphans fixture_players->players | ✅ pass | blocking | 0 orphans |
| 4-integrity | no orphans stats_flat->fixture_players | ✅ pass | blocking | 0 orphans |
| 5-uniqueness | canonical fixture key unique (<=50 flagged ambiguous) | ✅ pass | blocking | 26 residual dup rows (multi-api ambiguous, flagged) |
| 5-uniqueness | match_stats one row per fixture | ✅ pass | blocking |  |
| 6-entity-dedup | no duplicate api_football_id in teams | ✅ pass | blocking | 0 dup groups |
| 6-entity-dedup | no duplicate api_football_id in players | ✅ pass | blocking | 0 dup groups |
| 6-entity-dedup | no duplicate api_football_id in leagues | ✅ pass | blocking | 0 dup groups |
| 7-cross-source | fixture goal-conflicts logged (<=5) | ✅ pass | info | 1 pre-reconciliation goal conflict logged in audit_fixture_conflicts |
| 8-temporal | no played fixture with future date | ✅ pass | blocking | 0 future-dated played |
| 8-temporal | scheduled fixtures have no goals | ✅ pass | warning |  |
| 8-temporal | dates within [2010, now+2y] | ✅ pass | blocking |  |
| 9-leakage | match_stats.known_at present | ✅ pass | blocking |  |
| 9-leakage | match_stats known_at after kickoff | ✅ pass | blocking | 0 facts knowable pre-kickoff |
| 10-provenance | fixtures carry in_csv/in_pq provenance | ✅ pass | blocking |  |
| 10-provenance | odds carry source | ✅ pass | warning |  |
| 10-provenance | match_stats carry xg_covered flag | ✅ pass | blocking |  |
| 11-distribution | BTTS rate in [0.45,0.57] | ✅ pass | blocking | btts=0.5123 |
| 11-distribution | home win rate in [0.40,0.50] (home advantage) | ✅ pass | warning | home_win=0.4436 |
| 11-distribution | xG<->goals corr >= 0.30 (post fake-zero fix) | ✅ pass | warning | corr=0.3858 |
| 12-anomaly | no impossible scores (>30) | ✅ pass | blocking | 0 rows |
| 12-anomaly | player minutes in [0,130] | ✅ pass | warning | 0 rows |
| 12-anomaly | player rating in [0,10] | ✅ pass | warning | 0 rows |
| C-cloudbet | every Cloudbet competition accounted for | ✅ pass | blocking | 285 competitions, 242 mapped/excluded, 43 logged-unmapped |
| C-cloudbet | Cloudbet-covered leagues ingested (<=20 residual) | ✅ pass | warning | 10 Cloudbet leagues still missing from dataset (logged worklist) |
