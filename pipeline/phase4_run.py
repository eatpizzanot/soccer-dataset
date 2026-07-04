"""Phase 4 driver: run the bounded fixtures ingest (refresh + missing leagues).

Scope (bounded, high-value, re-runnable):
  * refresh existing leagues for recent seasons (bring results to the present);
  * ingest missing (Cloudbet-covered) leagues for recent seasons (fixtures-first: goals/BTTS +
    new teams).
Full historical backfill = widen the season lists here; the pipeline is idempotent.
"""
from __future__ import annotations

import io
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pipeline import config as c  # noqa: E402
from pipeline import staging  # noqa: E402
from pipeline.phase4_ingest import ingest  # noqa: E402

REFRESH_SEASONS = [2025, 2026]
MISSING_SEASONS = [2024, 2025]


def main() -> None:
    con = staging.connect(read_only=True)
    existing = [int(r[0]) for r in con.execute(
        "SELECT DISTINCT api_football_id FROM stg_leagues WHERE api_football_id IS NOT NULL AND id < 100000000"
    ).fetchall()]
    con.close()

    worklist = json.loads((c.BUILD_DIR / "apifootball" / "ingest_worklist.json").read_text(encoding="utf-8"))
    missing = [int(w["af_league_id"]) for w in worklist]

    refresh_pairs = [(lid, s) for lid in existing for s in REFRESH_SEASONS]
    missing_pairs = [(lid, s) for lid in missing for s in MISSING_SEASONS]

    print(f"refresh: {len(existing)} leagues x {len(REFRESH_SEASONS)} seasons = {len(refresh_pairs)} calls")
    print(f"missing: {len(missing)} leagues x {len(MISSING_SEASONS)} seasons = {len(missing_pairs)} calls")

    r1 = ingest(refresh_pairs, label="refresh")
    r2 = ingest(missing_pairs, label="missing")
    print(json.dumps({"refresh": r1, "missing": r2}, indent=2))


if __name__ == "__main__":
    main()
