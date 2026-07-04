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

- **563,441** fixtures (538,386 played), **271** leagues,
  **10,785** teams, 2011-01-15 - 2027-06-06.
- BTTS base rate **0.5100**. xG fake-zeros removed; `known_at` leakage guard;
  12-dimension QA gate (`QUALITY_REPORT.md`).

**Caveats:** league history is uneven — check `league_catalogue.history_status`
(full / recent_only / partial) per league. `xg` is a **crude provider approximation**
(shots-by-zone, not Opta/StatsBomb grade) and is `NULL` for uncovered league-seasons; never
treat missing xG as `0`.

```python
from datasets import load_dataset
ds = load_dataset("eatpizzanot/soccer-dataset", "fixtures")
```

See `data_dictionary.md` for every column. Licensed CC-BY-4.0; cite API-Football and
football-data.co.uk.
