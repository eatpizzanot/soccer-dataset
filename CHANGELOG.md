# Changelog

All notable changes to this dataset are documented here. Versioning follows [SemVer](https://semver.org/).

## [1.0.0] - 2026-07-05

### Added
- Reconciled the CSV + Parquet source snapshots into a single canonical set
  (**673,966 fixtures**, 644,901 played, history 2008-2027).
- **Full historical backfill** via API-Football: ingested 127 missing Cloudbet-covered leagues,
  then deepened every league to its full available history (453 missing league-seasons across
  108 leagues) plus per-fixture `match_stats` + lineups. Per-league `history_status`
  (full / recent_only / partial) recorded in `league_catalogue`.
- `xg_training` table: team-match long format (shot aggregates -> real xG, covered leagues only)
  for lite-xG modelling.
- `league_catalogue` reconciling the dataset x API-Football (1,235) x Cloudbet (285) universe.
- `known_at` leakage-guard timestamps; per-row provenance flags (`xg_covered` / `xg_nulled`).
- Source-of-truth Postgres DB (`probodds_soccer`) + parquet export layer.
- Frictionless `datapackage.json`, Croissant metadata, per-table samples, data dictionary,
  `QUALITY_REPORT.md`, CI, and a re-runnable `scripts/restore.py`.

### Fixed
- **xG fake-zero landmine**: nulled provider xG for non-covered league-seasons
  (xG<->goals correlation 0.22 -> 0.39). Documented that provider xG is a coarse shots-by-zone
  estimate (`~0.115*inside + 0.035*outside + 0.648*pen`, R^2~1.0), not a per-shot model.
- Deduplicated 121k+ cross-source duplicate fixture rows; merged 145 duplicate football-data teams.
- Dropped 25 "team-plays-itself" fixtures (upstream provider club-merger over-merge) with an
  audit trail; added a blocking `home_team_id <> away_team_id` QA gate.
- Dropped invalid odds (<=1) and implausible xG (>6) / pass-accuracy (>100) values.

### Removed
- Internal betting logs (`operator_actions`, `settlement_events`, `bankroll_snapshots`) - private;
  also purged from git history.
- Large data files from Git; full data now distributed via Hugging Face Datasets.
