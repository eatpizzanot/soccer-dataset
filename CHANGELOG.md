# Changelog

All notable changes to this dataset are documented here. Versioning follows [SemVer](https://semver.org/).

## [1.0.0] - 2026-07-05

### Added
- Reconciled CSV + Parquet source snapshots into a single canonical set (673,966 fixtures).
- Ingested 127 additional leagues via API-Football and refreshed results to the present.
- `league_catalogue` reconciling the dataset x API-Football (1,235) x Cloudbet (285) league universe.
- `known_at` leakage-guard timestamps; per-row provenance flags; `QUALITY_REPORT.md`.
- Frictionless `datapackage.json`, Croissant metadata, per-table samples, data dictionary.

### Fixed
- **xG fake-zero landmine**: nulled provider xG for non-covered league-seasons
  (xG<->goals correlation 0.22 -> 0.39).
- Deduplicated 121k+ cross-source duplicate fixture rows; merged 145 duplicate football-data teams.
- Dropped invalid odds (<=1) and implausible xG (>6) / pass-accuracy (>100) values.

### Removed
- Internal betting logs (`operator_actions`, `settlement_events`, `bankroll_snapshots`) - private.
- Large data files from Git; full data now distributed via Hugging Face Datasets.
