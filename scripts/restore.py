"""Re-runnable, idempotent restoration orchestrator (NOT a scheduled service).

Runs the full pipeline end to end:

    reconcile -> [ingest] -> integrate -> clean -> materialize -> discover -> qa -> publish

Usage:
    python scripts/restore.py                # full run (skips the API ingest by default)
    python scripts/restore.py --with-ingest  # also refresh/ingest leagues from API-Football
    python scripts/restore.py --stages qa    # run a single stage
    python scripts/restore.py --no-gate      # do not stop on QA failure

Every stage is idempotent; the QA stage returns non-zero on a blocking failure and, unless
``--no-gate`` is set, aborts before publishing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import (  # noqa: E402
    materialize, phase1_reconcile, phase3_clean, phase4_discover, phase4_integrate,
    phase6_publish, qa,
)

ALL_STAGES = ["reconcile", "ingest", "backfill_fixtures", "backfill_stats", "integrate",
              "clean", "materialize", "discover", "qa", "publish"]


def run_stage(name: str, with_ingest: bool, no_gate: bool) -> None:
    print(f"\n{'='*72}\n>>> STAGE: {name}\n{'='*72}", flush=True)
    if name == "reconcile":
        phase1_reconcile.main()
    elif name == "ingest":
        if with_ingest:
            from pipeline.phase4_run import main as ingest_main
            ingest_main()
        else:
            print("  (skipped; pass --with-ingest to hit API-Football)")
    elif name == "backfill_fixtures":
        if with_ingest:
            from pipeline.phase4_backfill import main as bf_main
            bf_main()
        else:
            print("  (skipped; --with-ingest for full-history fixtures backfill)")
    elif name == "backfill_stats":
        if with_ingest:
            import subprocess
            subprocess.run([sys.executable, "-m", "pipeline.phase4_backfill_stats", "--run"], check=False)
        else:
            print("  (skipped; --with-ingest for per-fixture stats+lineups backfill)")
    elif name == "integrate":
        phase4_integrate.main()
    elif name == "clean":
        phase3_clean.main()
    elif name == "materialize":
        materialize.main()
    elif name == "discover":
        phase4_discover.main()
    elif name == "qa":
        rc = qa.main()
        if rc != 0 and not no_gate:
            print("\nQA GATE FAILED - aborting before publish. Use --no-gate to override.")
            raise SystemExit(rc)
    elif name == "publish":
        phase6_publish.main()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--with-ingest", action="store_true", help="run the API-Football ingest stage")
    ap.add_argument("--no-gate", action="store_true", help="do not abort on QA failure")
    ap.add_argument("--stages", nargs="*", choices=ALL_STAGES, help="run only these stages")
    args = ap.parse_args()
    stages = args.stages or ALL_STAGES
    for s in stages:
        run_stage(s, args.with_ingest, args.no_gate)
    print("\nDone.")


if __name__ == "__main__":
    main()
