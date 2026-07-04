"""Phase 4 backfill driver: per-fixture match_stats + lineups for stats-covered league-seasons.

Selects PLAYED fixtures (from the ingested set) whose (league, season) has API-Football
statistics coverage, and fetches /fixtures/statistics (+xG) and /fixtures/lineups for each.
Resumable (skips fixtures already in raw_ingest_fx_done). Respects the daily budget: pass an
optional call budget; re-run to continue.

    python -m pipeline.phase4_backfill_stats            # size only
    python -m pipeline.phase4_backfill_stats --run [--max-fixtures N]
"""
from __future__ import annotations

import argparse
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pipeline import config as c  # noqa: E402
from pipeline import staging  # noqa: E402
from pipeline.phase4_ingest import ingest_stats_lineups_parallel  # noqa: E402


def covered_league_seasons() -> set[tuple[int, int]]:
    raw = json.loads((c.BUILD_DIR / "apifootball" / "leagues.json").read_text(encoding="utf-8"))
    s: set[tuple[int, int]] = set()
    for r in raw:
        lid = r["league"]["id"]
        for se in r["seasons"]:
            cov = (se.get("coverage", {}).get("fixtures", {}) or {}).get("statistics_fixtures")
            if cov and se.get("year") is not None:
                s.add((lid, int(se["year"])))
    return s


def target_fixture_ids() -> list[int]:
    covered = covered_league_seasons()
    con = staging.connect(read_only=True)
    rows = con.execute("""
        SELECT api_football_id, league_af_id, season FROM raw_ingest_fixtures
        WHERE goals_home IS NOT NULL AND status IN ('FT','AET','PEN')
          AND league_af_id IS NOT NULL AND season IS NOT NULL
    """).fetchall()
    done = {r[0] for r in con.execute(
        "SELECT api_football_id FROM raw_ingest_fx_done").fetchall()} if \
        con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='raw_ingest_fx_done'").fetchone()[0] else set()
    con.close()
    fids = [int(r[0]) for r in rows if (int(r[1]), int(r[2])) in covered and int(r[0]) not in done]
    return fids


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--max-fixtures", type=int, default=0, help="cap fixtures this pass (budget control)")
    args = ap.parse_args()

    fids = target_fixture_ids()
    print(f"stats-covered played fixtures pending: {len(fids)}  (~{2*len(fids):,} API calls at 2/fixture)")
    if not args.run:
        print("size-only; pass --run to fetch.")
        return
    if args.max_fixtures:
        fids = fids[: args.max_fixtures]
        print(f"this pass: {len(fids)} fixtures (~{2*len(fids):,} calls)")
    rep = ingest_stats_lineups_parallel(fids, label="backfill-stats")
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
