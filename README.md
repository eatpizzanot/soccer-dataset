# Global Football Data Lake

**A comprehensive, open-source dataset of global football (soccer) match data spanning 14 years, 102 leagues, and 367,000+ fixtures.**

---

## Overview

| Metric | Value |
|---|---|
| **Fixtures** | 367,530 |
| **Date Range** | February 2012 – February 2026 |
| **Leagues / Competitions** | 102 |
| **Teams** | 5,890 |
| **Players** | 181,986 |
| **Player-Match Records** | 9,960,895 |
| **Match Stats Records** | 217,125 |
| **Odds Records** | 50,044 |
| **Countries** | 60+ |

All data is sourced from [API-Football](https://www.api-football.com/) and [Football-Data.co.uk](https://www.football-data.co.uk/), cross-referenced and deduplicated into a unified schema.

---

## File Inventory

Every table is provided in **both CSV and Parquet** format. Parquet files are significantly smaller and faster to load.

| File | Rows | CSV Size | Parquet Size | Description |
|---|---|---|---|---|
| `fixtures.csv` | 367,530 | 35 MB | 7.7 MB | Every match: date, teams, score, status |
| `match_stats.csv` | 217,125 | 12 MB | 4.2 MB | Per-match stats: shots, xG, corners, cards |
| `odds.csv` | 50,044 | 1.9 MB | 764 KB | Closing odds (1X2 market) |
| `fixture_lineups.csv` | 519,373 | 25 MB | 7.0 MB | Starting XI formations and coaches |
| `fixture_players.csv` | 9,960,895 | 577 MB | 100 MB | Every player appearance: minutes, rating |
| `fixture_players_stats_flat.csv` | 1,380,169 | 131 MB | 77 MB | Granular per-player stats (36 columns) |
| `players.csv` | 181,986 | 5.5 MB | 3.8 MB | Player registry: name, nationality, age |
| `teams.csv` | 5,890 | 332 KB | 228 KB | Team registry with Glicko-2 ratings |
| `leagues.csv` | 102 | 4 KB | 8 KB | League/competition registry |

**Total size:** ~790 MB (CSV) / ~200 MB (Parquet)

---

## Table Schemas

### `fixtures.csv`

The core table. One row per match.

| Column | Type | Description |
|---|---|---|
| `id` | int | Internal primary key |
| `api_football_id` | float | API-Football fixture ID (nullable for CSV-only fixtures) |
| `date` | datetime | Kickoff time (UTC) |
| `status` | string | Match status: `FT` (Full Time), `AET` (After Extra Time), `PEN` (Penalties) |
| `league_id` | int | Foreign key → `leagues.id` |
| `league_name` | string | League name (denormalized for convenience) |
| `league_country` | string | Country of the league |
| `home_team_id` | int | Foreign key → `teams.id` |
| `home_team` | string | Home team name |
| `away_team_id` | int | Foreign key → `teams.id` |
| `away_team` | string | Away team name |
| `goals_home` | float | Goals scored by home team |
| `goals_away` | float | Goals scored by away team |

**Status codes:**
- `FT` — Full Time (364,151 matches, 99.1%)
- `AET` — After Extra Time (1,522 matches — cup games)
- `PEN` — Decided by Penalties (1,857 matches — cup games)

---

### `match_stats.csv`

Detailed match statistics. One row per fixture. Covers ~59% of all fixtures (primarily post-2015 and major leagues).

| Column | Type | Description |
|---|---|---|
| `id` | int | Primary key |
| `fixture_id` | int | Foreign key → `fixtures.id` |
| `home_shots_total` | int | Total shots by home team |
| `away_shots_total` | int | Total shots by away team |
| `home_shots_on_goal` | int | Shots on target — home |
| `away_shots_on_goal` | int | Shots on target — away |
| `home_shots_inside_box` | int | Shots from inside the box — home |
| `away_shots_inside_box` | int | Shots from inside the box — away |
| `home_shots_outside_box` | int | Shots from outside the box — home |
| `away_shots_outside_box` | int | Shots from outside the box — away |
| `home_blocked_shots` | int | Blocked shots — home |
| `away_blocked_shots` | int | Blocked shots — away |
| `home_corners` | int | Corner kicks — home |
| `away_corners` | int | Corner kicks — away |
| `home_yellow_cards` | int | Yellow cards — home |
| `away_yellow_cards` | int | Yellow cards — away |
| `home_red_cards` | int | Red cards — home |
| `away_red_cards` | int | Red cards — away |
| `home_penalties` | int | Penalties awarded — home |
| `away_penalties` | int | Penalties awarded — away |
| `home_xg` | float | Expected Goals (xG) — home. **Available for ~142,274 matches (65%).** |
| `away_xg` | float | Expected Goals (xG) — away |

**Note on xG:** API-Football provides xG for most top-tier leagues post-2017. Older matches and minor leagues may have `NULL` xG values. Use with appropriate null-handling.

---

### `odds.csv`

Pre-match closing odds for the 1X2 (Match Result) market.

| Column | Type | Description |
|---|---|---|
| `id` | int | Primary key |
| `fixture_id` | int | Foreign key → `fixtures.id` |
| `home_win` | float | Decimal odds for Home Win |
| `draw` | float | Decimal odds for Draw |
| `away_win` | float | Decimal odds for Away Win |
| `bookmaker` | string | Source bookmaker (see below) |
| `source` | string | Data provenance: `CSV` or `The-Odds-API` |

**Bookmaker distribution:**

| Bookmaker | Records | Source |
|---|---|---|
| Bet365 | 33,862 | Football-Data.co.uk CSVs |
| Pinnacle | 13,427 | The Odds API |
| Betfair | 1,455 | The Odds API |
| 888sport | 700 | The Odds API |
| William Hill | 234 | The Odds API |
| Other | 366 | The Odds API |

**Coverage:** Odds are available for ~13.6% of all fixtures. Coverage is highest for Tier 1/2 European leagues from 2015 onward.

**Converting to implied probability:**
```python
implied_prob = 1.0 / decimal_odds
# Normalize to remove overround:
total = (1/home_win) + (1/draw) + (1/away_win)
fair_prob_home = (1/home_win) / total
```

---

### `fixture_lineups.csv`

Starting formations and coaching staff. Two rows per fixture (one per team).

| Column | Type | Description |
|---|---|---|
| `id` | int | Primary key |
| `fixture_id` | int | Foreign key → `fixtures.id` |
| `team_id` | int | Foreign key → `teams.id` |
| `team_name` | string | Team name |
| `coach_name` | string | Head coach name |
| `coach_api_id` | float | API-Football coach ID |
| `formation` | string | Tactical formation (e.g., `4-3-3`, `3-5-2`, `5-4-1`) |

**Use cases:**
- Track formation changes over time (covariate drift detection)
- Identify coaching tenure and tactical shifts
- Feature engineering for match prediction models

---

### `fixture_players.csv`

Every player appearance in every match. The largest table (~10M rows).

| Column | Type | Description |
|---|---|---|
| `id` | int | Primary key |
| `fixture_id` | int | Foreign key → `fixtures.id` |
| `team_id` | int | Foreign key → `teams.id` |
| `player_id` | int | Foreign key → `players.id` |
| `player_name` | string | Player name |
| `is_starter` | bool | `True` = started, `False` = substitute |
| `position` | string | Position: `G` (Goalkeeper), `D` (Defender), `M` (Midfielder), `F` (Forward) |
| `number` | float | Shirt number |
| `captain` | bool | Whether the player was captain |
| `minutes` | float | Minutes played |
| `rating` | float | API-Football match rating (1.0 – 10.0 scale) |

**Starter vs Sub breakdown:** 5,680,636 starter appearances / 4,280,258 substitute appearances.

---

### `fixture_players_stats_flat.csv`

Granular per-player per-match statistics. One row per player appearance, with 36 statistical columns flattened from nested JSON.

| Column | Type | Description |
|---|---|---|
| `fixture_player_id` | int | Foreign key → `fixture_players.id` |
| `fixture_id` | int | Foreign key → `fixtures.id` |
| `player_id` | int | Foreign key → `players.id` |
| **Shooting** | | |
| `shots_total` | int | Total shots |
| `shots_on` | int | Shots on target |
| **Goals** | | |
| `goals_total` | int | Goals scored |
| `goals_assists` | int | Assists |
| `goals_conceded` | int | Goals conceded (goalkeepers) |
| `goals_saves` | int | Saves (goalkeepers) |
| **Passing** | | |
| `passes_total` | int | Total passes attempted |
| `passes_key` | int | Key passes (leading to a shot) |
| `passes_accuracy` | int | Pass accuracy percentage |
| **Dribbling** | | |
| `dribbles_attempts` | int | Dribble attempts |
| `dribbles_success` | int | Successful dribbles |
| `dribbles_past` | int | Times dribbled past (defenders) |
| **Duels** | | |
| `duels_total` | int | Total duels contested |
| `duels_won` | int | Duels won |
| **Discipline** | | |
| `cards_yellow` | int | Yellow cards received |
| `cards_red` | int | Red cards received |
| `fouls_committed` | int | Fouls committed |
| `fouls_drawn` | int | Fouls drawn |
| **Tackles** | | |
| `tackles_total` | int | Total tackles |
| `tackles_blocks` | int | Blocked shots/passes |
| `tackles_interceptions` | int | Interceptions |
| **Other** | | |
| `offsides` | int | Offsides |
| `penalty_scored` | int | Penalties scored |
| `penalty_missed` | int | Penalties missed |
| `penalty_saved` | int | Penalties saved (GK) |
| `penalty_won` | int | Penalties won |
| `penalty_commited` | int | Penalties conceded |
| **Game Info** | | |
| `games_minutes` | float | Minutes played |
| `games_number` | float | Shirt number |
| `games_position` | string | Position |
| `games_rating` | float | Match rating |
| `games_captain` | bool | Captain flag |
| `games_substitute` | bool | Came on as substitute |

---

### `players.csv`

Player registry. Unique players across all competitions.

| Column | Type | Description |
|---|---|---|
| `id` | int | Internal primary key |
| `api_football_id` | int | API-Football player ID |
| `name` | string | Full display name |
| `firstname` | string | First name (may be null) |
| `lastname` | string | Last name (may be null) |
| `age` | int | Age at time of data collection (may be null) |
| `nationality` | string | Nationality (may be null) |
| `height` | string | Height (may be null) |
| `weight` | string | Weight (may be null) |

---

### `teams.csv`

Team registry with Glicko-2 skill ratings.

| Column | Type | Description |
|---|---|---|
| `id` | int | Internal primary key |
| `name` | string | Team name |
| `api_football_id` | float | API-Football team ID |
| `fd_name` | string | Name used in Football-Data.co.uk CSVs (for cross-referencing) |
| `rating_mu` | float | Glicko-2 rating (mean). **Default: 1500.** Higher = stronger. |
| `rating_sigma` | float | Glicko-2 rating uncertainty. Lower = more confident rating. |

**Rating methodology:** Ratings were computed by chronologically replaying all 367K+ matches through the [openskill](https://github.com/Philihp/openskill.js) library (Plackett-Luce / Glicko-2 variant). International and continental cup fixtures serve as "bridges" to calibrate cross-league comparisons.

**Top-rated teams (as of Feb 2026):**
| Team | Rating (μ) |
|---|---|
| Argentina (NT) | 2,088 |
| Colombia (NT) | 1,950 |
| Senegal (NT) | 1,941 |
| Spain (NT) | 1,940 |
| Brazil (NT) | 1,912 |

---

### `leagues.csv`

League and competition registry.

| Column | Type | Description |
|---|---|---|
| `id` | int | Internal primary key |
| `name` | string | League name |
| `country` | string | Country |
| `fd_code` | string | Football-Data.co.uk identifier |
| `api_football_id` | int | API-Football league ID |

---

## League Coverage

### Domestic Leagues (81 leagues)

| Tier | Region | Leagues |
|---|---|---|
| **Tier 1** | Europe (Big 5) | Premier League, La Liga, Serie A, Ligue 1, Bundesliga |
| **Tier 2** | Europe (Strong) | Championship, Segunda Division, Serie B, Ligue 2, 2. Bundesliga, Eredivisie, Primeira Liga, Jupiler Pro League, Süper Lig, Scottish Premiership |
| **Tier 3** | Americas & Asia | MLS, Liga MX, J1 League, Serie A (Brazil), Liga Profesional (Argentina), K League 1, Saudi Pro League, A-League |
| **Tier 4** | Europe (Mid) | Eliteserien, Ekstraklasa, Allsvenskan, Superliga (Denmark), Super League 1 (Greece), HNL (Croatia), NB I (Hungary) |
| **Tier 5** | Emerging | Persian Gulf Pro League (Iran), PSL (South Africa), Botola Pro (Morocco), Super League (India), USL Championship, and 30+ more |

### International Competitions (11)
FIFA World Cup, UEFA Euro, UEFA Nations League, Copa America, AFCON, Asian Cup, World Cup Qualifiers (Europe/South America/CONCACAF), Euro Qualifiers, International Friendlies

### Continental Club Cups (6)
UEFA Champions League, UEFA Europa League, UEFA Conference League, Copa Libertadores, Copa Sudamericana, FIFA Club World Cup

### Domestic Cups (6)
FA Cup, Carabao Cup, Copa del Rey, DFB Pokal, Coppa Italia, Coupe de France

---

## Temporal Coverage

| Year | Fixtures | Notes |
|---|---|---|
| 2012 | 10,760 | Partial year (starts February) |
| 2013 | 16,101 | |
| 2014 | 17,364 | World Cup year |
| 2015 | 18,753 | |
| 2016 | 22,510 | Euro 2016 |
| 2017 | 25,409 | |
| 2018 | 26,598 | World Cup year |
| 2019 | 32,076 | |
| 2020 | 28,302 | COVID-19 impact (reduced fixtures, compressed schedules) |
| 2021 | 39,040 | Euro 2020 + catch-up fixtures |
| 2022 | 36,172 | World Cup year (Qatar) |
| 2023 | 32,157 | |
| 2024 | 29,403 | Euro 2024 |
| 2025 | 30,498 | |
| 2026 | 2,387 | Through February 10 |

---

## Data Quality Notes

1. **xG Coverage:** Expected Goals are available for ~65% of match_stats records. Coverage is highest for Tier 1/2 leagues from 2017 onward. Older and minor-league matches have `NULL` xG.

2. **Player Stats Coverage:** The `fixture_players` table has ~10M records but `fixture_players_stats_flat` has ~1.4M. The detailed per-player stats are only available for matches where the API provides the full statistics breakdown.

3. **Odds Coverage:** Only ~13.6% of fixtures have odds data. This is because (a) historical odds from Football-Data CSVs only cover major European leagues, and (b) The Odds API historical data starts from June 2020.

4. **Nullable Fields:** Several player fields (`firstname`, `lastname`, `age`, `nationality`, `height`, `weight`) may be null — especially for players in minor leagues.

5. **Team Ratings:** Glicko-2 ratings reflect the state at the time of the last data export. They are computed from the full match history. Teams with fewer matches have higher `rating_sigma` (less certainty).

---

## Entity Relationships

```
leagues (1) ──< fixtures (many)
teams (1) ──< fixtures.home_team_id (many)
teams (1) ──< fixtures.away_team_id (many)
fixtures (1) ──< match_stats (0..1)
fixtures (1) ──< odds (0..1)
fixtures (1) ──< fixture_lineups (0..2, one per team)
fixtures (1) ──< fixture_players (many, ~27 per match)
players (1) ──< fixture_players (many)
fixture_players (1) ──< fixture_players_stats_flat (0..1)
```

---

## Quick Start

### Python (Pandas)

```python
import pandas as pd

# Load core tables
fixtures = pd.read_parquet("fixtures.parquet")
stats = pd.read_parquet("match_stats.parquet")
odds = pd.read_parquet("odds.parquet")

# Merge fixtures with stats
df = fixtures.merge(stats, left_on="id", right_on="fixture_id", how="left", suffixes=("", "_stat"))

# Filter to Premier League, recent seasons
epl = df[(df["league_name"] == "Premier League") & (df["date"] >= "2020-01-01")]

print(f"EPL matches since 2020: {len(epl)}")
print(f"Average goals: {(epl['goals_home'] + epl['goals_away']).mean():.2f}")
```

### Python (Polars — faster for large files)

```python
import polars as pl

players = pl.read_parquet("fixture_players.parquet")
starters = players.filter(pl.col("is_starter") == True)

# Top players by average rating (min 50 appearances)
top = (
    starters
    .group_by("player_name")
    .agg([
        pl.col("rating").mean().alias("avg_rating"),
        pl.col("rating").count().alias("appearances"),
    ])
    .filter(pl.col("appearances") >= 50)
    .sort("avg_rating", descending=True)
    .head(20)
)
print(top)
```

### R

```r
library(arrow)

fixtures <- read_parquet("fixtures.parquet")
stats <- read_parquet("match_stats.parquet")

# Join and analyze
df <- merge(fixtures, stats, by.x = "id", by.y = "fixture_id", all.x = TRUE)
summary(df$home_xg)
```

---

## Use Cases

This dataset is suitable for:

- **Match outcome prediction** (1X2, Asian Handicap)
- **Goals modeling** (Over/Under, BTTS)
- **Expected Goals (xG) analysis** and model validation
- **Player performance tracking** and scouting
- **Team strength estimation** (Elo, Glicko-2, Bradley-Terry)
- **Tactical analysis** (formation trends, coaching impact)
- **Betting market research** (odds analysis, CLV modeling)
- **Network analysis** (passing networks from player co-occurrence)
- **Time-series forecasting** (form, regime detection)

---

## License & Attribution

This dataset is compiled from publicly available sources:
- **API-Football** (api-football.com) — match data, statistics, player data
- **Football-Data.co.uk** — historical odds and results

Please cite this dataset if you use it in research or publications. The data is provided as-is for research and educational purposes.

---

## Updates

This dataset was last exported on **February 10, 2026**. The underlying database is continuously updated as new matches are played.
