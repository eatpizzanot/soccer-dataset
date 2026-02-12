# Entity Relationships

```
leagues (1) ──< fixtures (many)
    └── id         └── league_id

teams (1) ──< fixtures.home_team_id (many)
teams (1) ──< fixtures.away_team_id (many)
    └── id         └── home_team_id / away_team_id

fixtures (1) ──< match_stats (0..1)
    └── id           └── fixture_id

fixtures (1) ──< odds (0..1)
    └── id        └── fixture_id

fixtures (1) ──< fixture_lineups (0..2, one per team)
    └── id           └── fixture_id

fixtures (1) ──< fixture_players (many, ~27 per match)
    └── id           └── fixture_id

players (1) ──< fixture_players (many)
    └── id          └── player_id

fixture_players (1) ──< fixture_players_stats_flat (0..1)
    └── id                └── fixture_player_id
```

## Join Examples

### Fixtures + Stats + Odds (Full match view)
```sql
SELECT f.*, s.home_xg, s.away_xg, o.home_win, o.draw, o.away_win
FROM fixtures f
LEFT JOIN match_stats s ON f.id = s.fixture_id
LEFT JOIN odds o ON f.id = o.fixture_id
WHERE f.status = 'FT';
```

### Player performance in a match
```sql
SELECT fp.player_name, fp.position, fp.minutes, fp.rating,
       ps.goals_total, ps.assists, ps.passes_total, ps.passes_accuracy
FROM fixture_players fp
LEFT JOIN fixture_players_stats_flat ps ON fp.id = ps.fixture_player_id
WHERE fp.fixture_id = 12345;
```

### Team lineup with formation
```sql
SELECT fl.formation, fl.coach_name, fp.player_name, fp.position, fp.number
FROM fixture_lineups fl
JOIN fixture_players fp ON fp.fixture_id = fl.fixture_id AND fp.team_id = fl.team_id
WHERE fl.fixture_id = 12345 AND fp.is_starter = true
ORDER BY fp.position, fp.number;
```
