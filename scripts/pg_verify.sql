\pset border 2
SELECT 'tables_in_public' AS metric, count(*)::text AS value FROM information_schema.tables WHERE table_schema='public'
UNION ALL SELECT 'fixtures', count(*)::text FROM fixtures
UNION ALL SELECT 'fixtures_played', count(*)::text FROM fixtures WHERE is_played
UNION ALL SELECT 'match_stats', count(*)::text FROM match_stats
UNION ALL SELECT 'fixture_players', count(*)::text FROM fixture_players
UNION ALL SELECT 'foreign_keys', count(*)::text FROM information_schema.table_constraints WHERE constraint_type='FOREIGN KEY' AND table_schema='public'
UNION ALL SELECT 'primary_keys', count(*)::text FROM information_schema.table_constraints WHERE constraint_type='PRIMARY KEY' AND table_schema='public'
UNION ALL SELECT 'indexes', count(*)::text FROM pg_indexes WHERE schemaname='public'
UNION ALL SELECT 'btts_rate', round(avg(CASE WHEN btts THEN 1 ELSE 0 END),4)::text FROM fixtures WHERE is_played
UNION ALL SELECT 'orphan_match_stats', count(*)::text FROM match_stats m LEFT JOIN fixtures f ON f.id=m.fixture_id WHERE f.id IS NULL
UNION ALL SELECT 'db_size', pg_size_pretty(pg_database_size('probodds_soccer'));
