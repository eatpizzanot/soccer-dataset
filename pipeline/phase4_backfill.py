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


def new_league_af_ids() -> list[int]:
    con = staging.connect(read_only=True)
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    src = "cln_leagues" if "cln_leagues" in have else "stg_leagues"
    ids = [int(r[0]) - OFF for r in con.execute(f"SELECT id FROM {src} WHERE id >= {OFF}").fetchall()]
    con.close()
    return ids


def seasons_by_league() -> dict[int, list[int]]:
    raw = json.loads((c.BUILD_DIR / "apifootball" / "leagues.json").read_text(encoding="utf-8"))
    return {r["league"]["id"]: sorted(s["year"] for s in r["seasons"]) for r in raw}


def main() -> None:
    new_ids = new_league_af_ids()
    sbl = seasons_by_league()
    pairs = [(lid, s) for lid in new_ids for s in sbl.get(lid, [])]
    print(f"new (recent-only) leagues: {len(new_ids)}")
    print(f"full-history league-season pairs: {len(pairs)}")
    rep = ingest(pairs, label="backfill-hist")
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
