# Data Dictionary

_Regenerated from the curated data. One section per table._

## `fixtures` (442,721 rows)

| Column | Type | Null % | Description |
|---|---|---|---|
| `id` | integer | 0.0% | Internal fixture primary key (stable across source snapshots). |
| `api_football_id` | integer | 16.5% | API-Football fixture id (null for football-data-only matches). |
| `date_utc` | datetime | 0.0% | Kick-off time, UTC (tz-naive). |
| `league_id` | integer | 0.0% | FK -> leagues.id. |
| `home_team_id` | integer | 0.0% | FK -> teams.id. |
| `away_team_id` | integer | 0.0% | FK -> teams.id. |
| `goals_home` | integer | 4.1% | Full-time home goals (null if not played). |
| `goals_away` | integer | 4.1% | Full-time away goals (null if not played). |
| `status` | string | 0.0% | Raw source status code. |
| `referee_name` | string | 65.4% | Referee (API-Football). |
| `referee_api_id` | integer | 100.0% | Referee API id. |
| `created_at` | datetime | 18.0% | Source row creation time. |
| `updated_at` | datetime | 18.0% | Source/refresh update time. |
| `in_csv` | boolean | 0.0% | Present in the CSV source snapshot. |
| `in_pq` | boolean | 0.0% | Present in the Parquet source snapshot. |
| `merged_rows` | integer | 0.0% | How many duplicate source rows were merged into this fixture. |
| `merged_football_data` | boolean | 0.0% | True if a football-data.co.uk copy was merged in. |
| `status_norm` | string | 0.0% | Normalized status enum: FT/AET/PEN/AWD/WO/NS/PST/CANC/ABD/SUSP/OTHER. |
| `is_played` | boolean | 0.0% | True if the match has a final result. |
| `calendar_year` | integer | 0.0% | Year of date_utc (used for xG coverage detection). |
| `btts` | boolean | 4.1% | Both-teams-to-score label (goals_home>0 AND goals_away>0); null if not played. |

## `match_stats` (270,573 rows)

| Column | Type | Null % | Description |
|---|---|---|---|
| `fixture_id` | integer | 0.0% | FK -> fixtures.id (one row per fixture). |
| `home_shots_total` | integer | 23.6% |  |
| `away_shots_total` | integer | 23.6% |  |
| `home_shots_on_goal` | integer | 23.6% |  |
| `away_shots_on_goal` | integer | 23.6% |  |
| `home_shots_inside_box` | integer | 26.9% |  |
| `away_shots_inside_box` | integer | 26.9% |  |
| `home_shots_outside_box` | integer | 26.9% |  |
| `away_shots_outside_box` | integer | 26.9% |  |
| `home_blocked_shots` | integer | 26.9% |  |
| `away_blocked_shots` | integer | 26.9% |  |
| `home_penalties` | integer | 26.9% |  |
| `away_penalties` | integer | 26.9% |  |
| `home_corners` | integer | 23.6% |  |
| `away_corners` | integer | 23.6% |  |
| `home_yellow_cards` | integer | 21.6% |  |
| `away_yellow_cards` | integer | 21.6% |  |
| `home_red_cards` | integer | 21.7% |  |
| `away_red_cards` | integer | 21.7% |  |
| `home_xg` | number | 53.8% | Home expected goals. NULL where the league-season is not xG-covered (fake zeros removed) or the value was implausible (>6). |
| `away_xg` | number | 53.8% | Away expected goals (see home_xg caveat). |
| `home_possession` | integer | 63.9% | Home possession % (0-100). |
| `away_possession` | integer | 63.9% | Away possession % (0-100). |
| `home_fouls` | integer | 49.0% |  |
| `away_fouls` | integer | 49.0% |  |
| `home_offsides` | integer | 52.8% |  |
| `away_offsides` | integer | 52.8% |  |
| `home_pass_accuracy` | integer | 65.9% | Home pass accuracy % (0-100). |
| `away_pass_accuracy` | integer | 65.9% | Away pass accuracy % (0-100). |
| `home_goals_ht` | integer | 6.0% | Home half-time goals. |
| `away_goals_ht` | integer | 6.0% | Away half-time goals. |
| `home_xg_ht` | number | 100.0% |  |
| `away_xg_ht` | number | 100.0% |  |
| `stats_fetched_at` | datetime | 77.7% | When stats were fetched from the provider. |
| `in_csv` | boolean | 0.0% |  |
| `in_pq` | boolean | 0.0% |  |
| `xg_covered` | boolean | 0.0% | False if this league-year was detected as lacking real xG coverage. |
| `xg_nulled` | boolean | 27.8% | True if the xG on this row was nulled by the fake-zero/anomaly fix. |
| `known_at` | datetime | 0.0% | Timestamp at which these post-match facts become known (kickoff + 105 min); use to avoid leakage in pre-match models. |

## `odds` (213,983 rows)

| Column | Type | Null % | Description |
|---|---|---|---|
| `fixture_id` | integer | 0.0% | FK -> fixtures.id. |
| `home_win` | number | 0.0% | Decimal odds, home win (>1). |
| `draw` | number | 0.0% | Decimal odds, draw (>1). |
| `away_win` | number | 0.0% | Decimal odds, away win (>1). |
| `bookmaker` | string | 0.0% | Bookmaker (96%+ Pinnacle closing). |
| `source` | string | 0.0% | Odds provenance. |
| `in_csv` | boolean | 0.0% |  |
| `in_pq` | boolean | 0.0% |  |
| `known_at` | datetime | 0.0% | Odds known at/around kick-off (closing line). |

## `fixture_lineups` (521,589 rows)

| Column | Type | Null % | Description |
|---|---|---|---|
| `fixture_id` | integer | 0.0% |  |
| `team_id` | integer | 0.0% |  |
| `team_name` | string | 0.4% |  |
| `coach_name` | string | 18.8% |  |
| `coach_api_id` | integer | 18.6% |  |
| `formation` | string | 39.4% |  |
| `in_csv` | boolean | 0.0% |  |
| `in_pq` | boolean | 0.0% |  |

## `teams` (8,810 rows)

| Column | Type | Null % | Description |
|---|---|---|---|
| `id` | integer | 0.0% | Internal team id. |
| `name` | string | 0.0% | Team name. |
| `api_football_id` | integer | 2.3% | API-Football team id. |
| `fd_name` | string | 89.1% | football-data.co.uk name (cross-reference). |
| `rating_mu` | number | 0.0% | Glicko-2 rating mean (default 1500). |
| `rating_sigma` | number | 27.5% | Glicko-2 uncertainty. |
| `in_csv` | boolean | 0.0% |  |
| `in_pq` | boolean | 0.0% |  |

## `players` (182,125 rows)

| Column | Type | Null % | Description |
|---|---|---|---|
| `id` | integer | 0.0% |  |
| `api_football_id` | integer | 0.0% |  |
| `name` | string | 0.0% |  |
| `firstname` | string | 100.0% |  |
| `lastname` | string | 100.0% |  |
| `age` | integer | 100.0% |  |
| `nationality` | string | 100.0% |  |
| `height` | string | 100.0% |  |
| `weight` | string | 100.0% |  |
| `photo` | string | 52.7% |  |
| `in_csv` | boolean | 0.0% |  |
| `in_pq` | boolean | 0.0% |  |

## `leagues` (271 rows)

| Column | Type | Null % | Description |
|---|---|---|---|
| `id` | integer | 0.0% | Internal league id. |
| `name` | string | 0.0% | League name. |
| `country` | string | 0.0% | Country. |
| `fd_code` | string | 46.9% | football-data.co.uk code. |
| `api_football_id` | integer | 0.0% | API-Football league id. |
| `in_csv` | boolean | 0.0% |  |
| `in_pq` | boolean | 0.0% |  |

## `fixture_players` (9,960,895 rows)

| Column | Type | Null % | Description |
|---|---|---|---|
| `id` | integer | 0.0% |  |
| `fixture_id` | integer | 0.0% |  |
| `team_id` | integer | 0.0% |  |
| `player_id` | integer | 0.0% |  |
| `player_name` | string | 0.0% |  |
| `is_starter` | boolean | 0.0% |  |
| `position` | string | 33.3% |  |
| `number` | number | 6.7% |  |
| `captain` | boolean | 0.0% |  |
| `minutes` | number | 60.1% |  |
| `rating` | number | 61.1% |  |

## `fixture_players_stats_flat` (4,903,099 rows)

| Column | Type | Null % | Description |
|---|---|---|---|
| `fixture_player_id` | integer | 0.0% |  |
| `fixture_id` | integer | 0.0% |  |
| `player_id` | integer | 0.0% |  |
| `cards_red` | integer | 0.0% |  |
| `cards_yellow` | integer | 0.0% |  |
| `dribbles_attempts` | number | 49.3% |  |
| `dribbles_past` | number | 71.5% |  |
| `dribbles_success` | number | 57.9% |  |
| `duels_total` | number | 28.4% |  |
| `duels_won` | number | 32.8% |  |
| `fouls_committed` | number | 46.9% |  |
| `fouls_drawn` | number | 48.7% |  |
| `games_captain` | boolean | 0.0% |  |
| `games_minutes` | number | 18.9% |  |
| `games_number` | number | 0.0% |  |
| `games_position` | string | 0.0% |  |
| `games_rating` | string | 20.5% |  |
| `games_substitute` | boolean | 0.0% |  |
| `goals_assists` | number | 77.9% |  |
| `goals_conceded` | number | 16.7% |  |
| `goals_saves` | number | 94.8% |  |
| `goals_total` | number | 93.1% |  |
| `offsides` | number | 94.2% |  |
| `passes_accuracy` | string | 20.5% |  |
| `passes_key` | number | 54.3% |  |
| `passes_total` | number | 19.8% |  |
| `penalty_commited` | number | 99.2% |  |
| `penalty_missed` | integer | 0.0% |  |
| `penalty_saved` | number | 94.4% |  |
| `penalty_scored` | integer | 0.0% |  |
| `penalty_won` | number | 99.4% |  |
| `shots_on` | number | 62.7% |  |
| `shots_total` | number | 53.6% |  |
| `tackles_blocks` | number | 77.1% |  |
| `tackles_interceptions` | number | 53.7% |  |
| `tackles_total` | number | 62.7% |  |

## `league_catalogue` (1,235 rows)

| Column | Type | Null % | Description |
|---|---|---|---|
| `af_league_id` | integer | 0.0% | API-Football league id. |
| `af_name` | string | 0.0% |  |
| `af_country` | string | 0.0% |  |
| `af_type` | string | 0.0% |  |
| `af_has_stats` | boolean | 0.0% | API-Football provides fixture statistics. |
| `min_season` | integer | 0.0% |  |
| `max_season` | integer | 0.0% |  |
| `in_dataset` | boolean | 0.0% | League present in this dataset. |
| `dataset_league_id` | number | 78.1% |  |
| `in_cloudbet` | boolean | 0.0% | Offered by Cloudbet. |
| `cloudbet_key` | string | 82.1% | Cloudbet competition key. |
| `cloudbet_name` | string | 82.1% | Cloudbet competition name. |
