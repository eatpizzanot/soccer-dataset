"""Phase 4 backfill driver: full-history fixtures for recent-only (newly-added) leagues.

The 127 Cloudbet-covered leagues added earlier were ingested recent-seasons-only. This pulls
every season API-Football offers for each (exact season list from leagues.json), fixtures-first.
Idempotent (INSERT OR REPLACE by fixture api id). Re-runnable / resumable.
"""
from __future__ import annotations

import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pipeline import config as c  # noqa: E402
from pipeline import staging  # noqa: E402
from pipeline.phase4_ingest import ingest  # noqa: E402

OFF = 100_000_000


def dataset_league_af_ids() -> list[int]:
    """All in-dataset leagues' API-Football ids (original + newly-added) — backfill every one's
    full available history so shallow originals get deepened too."""
    con = staging.connect(read_only=True)
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    src = "cln_leagues" if "cln_leagues" in have else "stg_leagues"
    ids = [int(r[0]) for r in con.execute(
        f"SELECT DISTINCT api_football_id FROM {src} WHERE api_football_id IS NOT NULL").fetchall()]
    con.close()
    return ids


def present_coverage() -> set[tuple[int, int]]:
    """Set of (af_league_id, calendar_year) already present in the dataset."""
    con = staging.connect(read_only=True)
    rows = con.execute("""
        SELECT l.api_football_id, f.calendar_year
        FROM cln_fixtures f JOIN cln_leagues l ON l.id = f.league_id
        WHERE l.api_football_id IS NOT NULL AND f.calendar_year IS NOT NULL
        GROUP BY 1, 2
    """).fetchall()
    con.close()
    return {(int(a), int(y)) for a, y in rows}


def seasons_by_league() -> dict[int, list[int]]:
    raw = json.loads((c.BUILD_DIR / "apifootball" / "leagues.json").read_text(encoding="utf-8"))
    return {r["league"]["id"]: sorted(s["year"] for s in r["seasons"]) for r in raw}


def main() -> None:
    ids = dataset_league_af_ids()
    sbl = seasons_by_league()
    present = present_coverage()
    # missing = available seasons we have no fixtures for (by calendar year)
    pairs = [(lid, s) for lid in ids for s in sbl.get(lid, []) if (lid, s) not in present]
    gap_leagues = len({lid for lid, _ in pairs})
    print(f"in-dataset leagues: {len(ids)}")
    print(f"missing league-season pairs to backfill: {len(pairs)} across {gap_leagues} leagues")
    rep = ingest(pairs, label="backfill-gaps")
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
