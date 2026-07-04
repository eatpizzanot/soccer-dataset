"""Lightweight CI gate: validate committed samples + metadata without the full dataset.

Runs in GitHub Actions on every push/PR. Checks:
  * every sample table validates against its pandera contract;
  * datapackage.json and croissant.json parse and reference every published table.
Exits non-zero on any failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import qa_pandera  # noqa: E402

PUBLISH_TABLES = [
    "fixtures", "match_stats", "odds", "fixture_lineups", "teams", "players",
    "leagues", "fixture_players", "fixture_players_stats_flat", "league_catalogue",
    "xg_training",
]

failures: list[str] = []


def check_samples() -> None:
    for tbl in qa_pandera.SCHEMAS:
        p = ROOT / "samples" / f"{tbl}.csv"
        if not p.exists():
            failures.append(f"missing sample {p.name}")
            continue
        df = pd.read_csv(p)
        ok, detail = qa_pandera.validate(tbl, df)
        print(f"  pandera {tbl:<16} {'ok' if ok else 'FAIL: ' + detail}")
        if not ok:
            failures.append(f"pandera {tbl}: {detail}")


def check_metadata() -> None:
    dp = json.loads((ROOT / "metadata" / "datapackage.json").read_text(encoding="utf-8"))
    names = {r["name"] for r in dp["resources"]}
    for t in PUBLISH_TABLES:
        if t not in names:
            failures.append(f"datapackage missing resource {t}")
    print(f"  datapackage.json: {len(dp['resources'])} resources")
    cr = json.loads((ROOT / "metadata" / "croissant.json").read_text(encoding="utf-8"))
    assert cr["@type"] == "sc:Dataset"
    print(f"  croissant.json: {len(cr['distribution'])} distributions")


def check_samples_present() -> None:
    for t in PUBLISH_TABLES:
        if not (ROOT / "samples" / f"{t}.csv").exists():
            failures.append(f"missing sample {t}.csv")


def main() -> int:
    print("CI check: samples + metadata")
    check_samples()
    check_samples_present()
    check_metadata()
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nAll CI checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
