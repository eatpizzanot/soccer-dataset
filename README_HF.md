---
license: cc-by-4.0
language:
  - en
pretty_name: Global Football (Soccer) Data Lake
task_categories:
  - tabular-classification
tags:
  - soccer
  - football
  - sports-analytics
  - betting
  - expected-goals
  - btts
size_categories:
  - 1M<n<10M
configs:
  - config_name: fixtures
    data_files: fixtures.parquet
  - config_name: match_stats
    data_files: match_stats.parquet
  - config_name: odds
    data_files: odds.parquet
  - config_name: fixture_lineups
    data_files: fixture_lineups.parquet
  - config_name: teams
    data_files: teams.parquet
  - config_name: players
    data_files: players.parquet
  - config_name: leagues
    data_files: leagues.parquet
  - config_name: fixture_players
    data_files: fixture_players.parquet
  - config_name: fixture_players_stats_flat
    data_files: fixture_players_stats_flat.parquet
  - config_name: league_catalogue
    data_files: league_catalogue.parquet
  - config_name: xg_training
    data_files: xg_training.parquet
---

# Global Football (Soccer) Data Lake

Cleaned, deduplicated, quality-gated football match data for BTTS / goals modelling.
Sources: API-Football + football-data.co.uk. Pipeline & docs:
https://github.com/eatpizzanot/soccer-dataset

- **673,991** fixtures (644,926 played), **271** leagues,
  **11,104** teams, 2008-06-07 - 2027-06-06.
- BTTS base rate **0.5063**. xG fake-zeros removed; `known_at` leakage guard;
  12-dimension QA gate (`QUALITY_REPORT.md`).

**Caveats:** league history is uneven — check `league_catalogue.history_status`
(full / recent_only / partial) per league. `xg` is a **coarse provider estimate, not a real
per-shot xG model**: API-Football xG is a deterministic shots-by-zone formula (empirically
`xg ≈ 0.115·shots_inside_box + 0.035·shots_outside_box + 0.648·penalties`, R²≈1.0), correlates
~0.4 with goals, and is `NULL` for uncovered league-seasons; never treat missing xG as `0`.

```python
from datasets import load_dataset
ds = load_dataset("eatpizzanot/soccer-dataset", "fixtures")
```

See `data_dictionary.md` for every column. Licensed CC-BY-4.0; cite API-Football and
football-data.co.uk.
