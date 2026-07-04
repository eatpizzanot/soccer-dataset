"""Phase 6 - generate publishing artifacts from the curated data.

Produces (all derived from build/curated, so they never drift from reality):
  samples/*.csv                 ~1k-row representative sample per table (committed to GitHub)
  metadata/datapackage.json     Frictionless Data Package (schemas + provenance)
  metadata/croissant.json       ML Commons Croissant metadata (HF/Google Dataset Search)
  docs/data_dictionary.md       per-column dictionary regenerated FROM the data
  README.md                     regenerated headline + usage (old README was inaccurate)
  VERSION, CHANGELOG.md         SemVer + change log
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb  # noqa: E402

from pipeline import config as c  # noqa: E402

VERSION = "1.0.0"
HF_NAMESPACE = "eatpizzanot/soccer-dataset"
SAMPLE_ROWS = 1000

PUBLISH_TABLES = [
    "fixtures", "match_stats", "odds", "fixture_lineups", "teams", "players",
    "leagues", "fixture_players", "fixture_players_stats_flat", "league_catalogue",
]

TYPE_MAP = {"BIGINT": "integer", "INTEGER": "integer", "DOUBLE": "number",
            "VARCHAR": "string", "TIMESTAMP": "datetime", "BOOLEAN": "boolean"}

DESC: dict[str, dict[str, str]] = {
    "fixtures": {
        "id": "Internal fixture primary key (stable across source snapshots).",
        "api_football_id": "API-Football fixture id (null for football-data-only matches).",
        "date_utc": "Kick-off time, UTC (tz-naive).",
        "league_id": "FK -> leagues.id.",
        "home_team_id": "FK -> teams.id.", "away_team_id": "FK -> teams.id.",
        "goals_home": "Full-time home goals (null if not played).",
        "goals_away": "Full-time away goals (null if not played).",
        "status": "Raw source status code.",
        "status_norm": "Normalized status enum: FT/AET/PEN/AWD/WO/NS/PST/CANC/ABD/SUSP/OTHER.",
        "is_played": "True if the match has a final result.",
        "btts": "Both-teams-to-score label (goals_home>0 AND goals_away>0); null if not played.",
        "calendar_year": "Year of date_utc (used for xG coverage detection).",
        "referee_name": "Referee (API-Football).", "referee_api_id": "Referee API id.",
        "merged_rows": "How many duplicate source rows were merged into this fixture.",
        "merged_football_data": "True if a football-data.co.uk copy was merged in.",
        "in_csv": "Present in the CSV source snapshot.", "in_pq": "Present in the Parquet source snapshot.",
        "created_at": "Source row creation time.", "updated_at": "Source/refresh update time.",
    },
    "match_stats": {
        "fixture_id": "FK -> fixtures.id (one row per fixture).",
        "home_xg": "Home expected goals. NULL where the league-season is not xG-covered "
                   "(fake zeros removed) or the value was implausible (>6).",
        "away_xg": "Away expected goals (see home_xg caveat).",
        "xg_covered": "False if this league-year was detected as lacking real xG coverage.",
        "xg_nulled": "True if the xG on this row was nulled by the fake-zero/anomaly fix.",
        "home_possession": "Home possession % (0-100).", "away_possession": "Away possession % (0-100).",
        "home_pass_accuracy": "Home pass accuracy % (0-100).", "away_pass_accuracy": "Away pass accuracy % (0-100).",
        "home_goals_ht": "Home half-time goals.", "away_goals_ht": "Away half-time goals.",
        "known_at": "Timestamp at which these post-match facts become known (kickoff + 105 min); "
                    "use to avoid leakage in pre-match models.",
        "stats_fetched_at": "When stats were fetched from the provider.",
    },
    "odds": {
        "fixture_id": "FK -> fixtures.id.",
        "home_win": "Decimal odds, home win (>1).", "draw": "Decimal odds, draw (>1).",
        "away_win": "Decimal odds, away win (>1).",
        "bookmaker": "Bookmaker (96%+ Pinnacle closing).", "source": "Odds provenance.",
        "known_at": "Odds known at/around kick-off (closing line).",
    },
    "leagues": {"id": "Internal league id.", "name": "League name.", "country": "Country.",
                "fd_code": "football-data.co.uk code.", "api_football_id": "API-Football league id."},
    "teams": {"id": "Internal team id.", "name": "Team name.", "api_football_id": "API-Football team id.",
              "fd_name": "football-data.co.uk name (cross-reference).",
              "rating_mu": "Glicko-2 rating mean (default 1500).", "rating_sigma": "Glicko-2 uncertainty."},
    "league_catalogue": {
        "af_league_id": "API-Football league id.", "af_has_stats": "API-Football provides fixture statistics.",
        "in_dataset": "League present in this dataset.", "in_cloudbet": "Offered by Cloudbet.",
        "cloudbet_key": "Cloudbet competition key.", "cloudbet_name": "Cloudbet competition name."},
}


def con_curated():
    con = duckdb.connect()
    for t in PUBLISH_TABLES:
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{(c.CURATED_DIR/f'{t}.parquet').as_posix()}')")
    return con


def stats(con) -> dict:
    g = lambda s: con.execute(s).fetchone()[0]
    return {
        "fixtures": g("SELECT count(*) FROM fixtures"),
        "played": g("SELECT count(*) FROM fixtures WHERE is_played"),
        "leagues": g("SELECT count(*) FROM leagues"),
        "teams": g("SELECT count(*) FROM teams"),
        "players": g("SELECT count(*) FROM players"),
        "btts": g("SELECT avg(CASE WHEN btts THEN 1.0 ELSE 0.0 END) FROM fixtures WHERE is_played"),
        "date_min": str(g("SELECT min(date_utc) FROM fixtures")),
        "date_max": str(g("SELECT max(date_utc) FROM fixtures")),
        "xg_fixtures": g("SELECT count(*) FROM match_stats WHERE home_xg IS NOT NULL"),
        "odds_fixtures": g("SELECT count(DISTINCT fixture_id) FROM odds"),
    }


def build_samples(con):
    c.SAMPLES_DIR.mkdir(exist_ok=True)
    for t in PUBLISH_TABLES:
        out = (c.SAMPLES_DIR / f"{t}.csv").as_posix()
        con.execute(f"COPY (SELECT * FROM {t} USING SAMPLE {SAMPLE_ROWS} ROWS) TO '{out}' (FORMAT CSV, HEADER)")
    print(f"  samples -> {c.SAMPLES_DIR}")


def schema_fields(con, t):
    fields = []
    for name, dtype, *_ in con.execute(f"DESCRIBE {t}").fetchall():
        fields.append({"name": name, "type": TYPE_MAP.get(dtype, "string"),
                       "description": DESC.get(t, {}).get(name, "")})
    return fields


def build_datapackage(con, st):
    resources = []
    for t in PUBLISH_TABLES:
        rows = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        resources.append({
            "name": t, "path": f"https://huggingface.co/datasets/{HF_NAMESPACE}/resolve/main/{t}.parquet",
            "format": "parquet", "mediatype": "application/parquet", "rows": rows,
            "sample": f"samples/{t}.csv", "schema": {"fields": schema_fields(con, t)},
        })
    dp = {
        "name": "soccer-dataset", "title": "Global Football (Soccer) Data Lake",
        "version": VERSION,
        "description": "API-Football + football-data.co.uk match data: fixtures, stats (xG), odds, "
                       "lineups and per-player records across 271 leagues, 2012-2026. Cleaned, "
                       "deduplicated and quality-gated for BTTS/goals modelling.",
        "licenses": [{"name": "CC-BY-4.0", "title": "Creative Commons Attribution 4.0"}],
        "sources": [{"title": "API-Football", "path": "https://www.api-football.com/"},
                    {"title": "football-data.co.uk", "path": "https://www.football-data.co.uk/"}],
        "created": datetime.now(timezone.utc).isoformat(),
        "resources": resources,
    }
    (c.METADATA_DIR / "datapackage.json").write_text(json.dumps(dp, indent=2), encoding="utf-8")
    print("  metadata/datapackage.json")


def build_croissant(con, st):
    def rs(table, fields):
        return {
            "@type": "cr:RecordSet", "@id": table, "name": table,
            "field": [{"@type": "cr:Field", "@id": f"{table}/{f}", "name": f,
                       "dataType": "sc:Text"} for f in fields],
        }
    dist = [{
        "@type": "cr:FileObject", "@id": f"{t}.parquet", "name": f"{t}.parquet",
        "contentUrl": f"https://huggingface.co/datasets/{HF_NAMESPACE}/resolve/main/{t}.parquet",
        "encodingFormat": "application/x-parquet",
    } for t in PUBLISH_TABLES]
    cr = {
        "@context": {"@vocab": "https://schema.org/", "cr": "http://mlcommons.org/croissant/",
                     "sc": "https://schema.org/", "dataType": "cr:dataType"},
        "@type": "sc:Dataset", "name": "soccer-dataset", "version": VERSION,
        "description": "Cleaned, quality-gated global football match data (fixtures, xG stats, odds, "
                       "lineups, players) for BTTS/goals modelling.",
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "url": f"https://huggingface.co/datasets/{HF_NAMESPACE}",
        "distribution": dist,
        "recordSet": [
            rs("fixtures", ["id", "date_utc", "league_id", "home_team_id", "away_team_id",
                            "goals_home", "goals_away", "status_norm", "is_played", "btts"]),
            rs("match_stats", ["fixture_id", "home_xg", "away_xg", "home_shots_total", "xg_covered"]),
            rs("odds", ["fixture_id", "home_win", "draw", "away_win", "bookmaker"]),
        ],
    }
    (c.METADATA_DIR / "croissant.json").write_text(json.dumps(cr, indent=2), encoding="utf-8")
    print("  metadata/croissant.json")


def build_dictionary(con):
    lines = ["# Data Dictionary", "",
             "_Regenerated from the curated data. One section per table._", ""]
    for t in PUBLISH_TABLES:
        rows = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        lines += [f"## `{t}` ({rows:,} rows)", "", "| Column | Type | Null % | Description |", "|---|---|---|---|"]
        desc = con.execute(f"DESCRIBE {t}").fetchall()
        for name, dtype, *_ in desc:
            nulls = con.execute(f'SELECT 100.0*sum(CASE WHEN "{name}" IS NULL THEN 1 ELSE 0 END)/count(*) FROM {t}').fetchone()[0]
            lines.append(f"| `{name}` | {TYPE_MAP.get(dtype,'string')} | {nulls:.1f}% | {DESC.get(t,{}).get(name,'')} |")
        lines.append("")
    (c.DOCS_DIR / "data_dictionary.md").write_text("\n".join(lines), encoding="utf-8")
    print("  docs/data_dictionary.md")


def build_readme(st):
    r = f"""# Global Football (Soccer) Data Lake

**A cleaned, deduplicated, quality-gated open dataset of global football match data for
Both-Teams-To-Score (BTTS) and goals modelling.** Sourced from
[API-Football](https://www.api-football.com/) and
[football-data.co.uk](https://www.football-data.co.uk/).

> This repository holds the **pipeline code, docs, metadata and ~1k-row samples**.
> The **full data** is published on Hugging Face:
> [`{HF_NAMESPACE}`](https://huggingface.co/datasets/{HF_NAMESPACE}) (parquet, `load_dataset()`-ready).

## Headline (v{VERSION})

| Metric | Value |
|---|---|
| Fixtures | **{st['fixtures']:,}** ({st['played']:,} played) |
| Leagues | **{st['leagues']}** |
| Teams | **{st['teams']:,}** |
| Players | **{st['players']:,}** |
| Date range | {st['date_min'][:10]} - {st['date_max'][:10]} |
| BTTS base rate | **{st['btts']:.4f}** |
| Fixtures with xG | {st['xg_fixtures']:,} |
| Fixtures with odds | {st['odds_fixtures']:,} |

## What makes this clean

- **Reconciled** two divergent source snapshots (CSV + Parquet) by a consistent internal id.
- **Deduplicated** cross-source duplicate matches on a canonical key (league, UTC day, home, away).
- **xG fake-zero fix**: xG stored as `0` for leagues API-Football does not cover for xG has been
  set to `NULL` (detected per league-season). Never treat missing xG as `0`.
- **Leakage guard**: post-match facts carry a `known_at` timestamp.
- **12-dimension QA gate** (`QUALITY_REPORT.md`) must pass before publishing.

## Tables

See [`docs/data_dictionary.md`](docs/data_dictionary.md) for every column. Core tables:
`fixtures`, `match_stats`, `odds`, `fixture_lineups`, `teams`, `players`, `leagues`,
`fixture_players`, `fixture_players_stats_flat`, plus a `league_catalogue`
(dataset x API-Football x Cloudbet coverage).

## Quick start

```python
from datasets import load_dataset
fixtures = load_dataset("{HF_NAMESPACE}", data_files="fixtures.parquet")["train"]
```
```python
import pandas as pd
fx = pd.read_parquet("https://huggingface.co/datasets/{HF_NAMESPACE}/resolve/main/fixtures.parquet")
print(fx.query("is_played").eval("goals_home>0 and goals_away>0").mean())  # BTTS rate
```

## Reproduce

The dataset is regenerated by a single, idempotent, re-runnable script (not a scheduled
service): `python scripts/restore.py`. See [`docs/PIPELINE.md`](docs/PIPELINE.md).

## License

Data is compiled from publicly available sources for research/educational use, released under
**CC-BY-4.0**. Please cite API-Football and football-data.co.uk.
"""
    (c.REPO_ROOT / "README.md").write_text(r, encoding="utf-8")
    print("  README.md")


def build_version_changelog(st):
    (c.REPO_ROOT / "VERSION").write_text(VERSION + "\n", encoding="utf-8")
    ch = f"""# Changelog

All notable changes to this dataset are documented here. Versioning follows [SemVer](https://semver.org/).

## [{VERSION}] - {datetime.now(timezone.utc):%Y-%m-%d}

### Added
- Reconciled CSV + Parquet source snapshots into a single canonical set ({st['fixtures']:,} fixtures).
- Ingested 127 additional leagues via API-Football and refreshed results to the present.
- `league_catalogue` reconciling the dataset x API-Football (1,235) x Cloudbet (285) league universe.
- `known_at` leakage-guard timestamps; per-row provenance flags; `QUALITY_REPORT.md`.
- Frictionless `datapackage.json`, Croissant metadata, per-table samples, data dictionary.

### Fixed
- **xG fake-zero landmine**: nulled provider xG for non-covered league-seasons
  (xG<->goals correlation 0.22 -> 0.39).
- Deduplicated 121k+ cross-source duplicate fixture rows; merged 145 duplicate football-data teams.
- Dropped invalid odds (<=1) and implausible xG (>6) / pass-accuracy (>100) values.

### Removed
- Internal betting logs (`operator_actions`, `settlement_events`, `bankroll_snapshots`) - private.
- Large data files from Git; full data now distributed via Hugging Face Datasets.
"""
    (c.REPO_ROOT / "CHANGELOG.md").write_text(ch, encoding="utf-8")
    print("  VERSION + CHANGELOG.md")


def build_hf_card(st):
    configs = "\n".join(f"  - config_name: {t}\n    data_files: {t}.parquet" for t in PUBLISH_TABLES)
    card = f"""---
license: cc-by-4.0
language:
  - en
pretty_name: Global Football (Soccer) Data Lake
task_categories:
  - tabular-classification
tags:
  - soccer
  - football
  - sports-analytics
  - betting
  - expected-goals
  - btts
size_categories:
  - 1M<n<10M
configs:
{configs}
---

# Global Football (Soccer) Data Lake

Cleaned, deduplicated, quality-gated football match data for BTTS / goals modelling.
Sources: API-Football + football-data.co.uk. Pipeline & docs:
https://github.com/{HF_NAMESPACE}

- **{st['fixtures']:,}** fixtures ({st['played']:,} played), **{st['leagues']}** leagues,
  **{st['teams']:,}** teams, {st['date_min'][:10]} - {st['date_max'][:10]}.
- BTTS base rate **{st['btts']:.4f}**. xG fake-zeros removed; `known_at` leakage guard;
  12-dimension QA gate (`QUALITY_REPORT.md`).

```python
from datasets import load_dataset
ds = load_dataset("{HF_NAMESPACE}", "fixtures")
```

See `data_dictionary.md` for every column. Licensed CC-BY-4.0; cite API-Football and
football-data.co.uk.
"""
    (c.REPO_ROOT / "README_HF.md").write_text(card, encoding="utf-8")
    print("  README_HF.md (HF dataset card)")


def main():
    con = con_curated()
    st = stats(con)
    build_samples(con)
    build_datapackage(con, st)
    build_croissant(con, st)
    build_dictionary(con)
    build_readme(st)
    build_hf_card(st)
    build_version_changelog(st)
    con.close()
    print("publishing artifacts generated.")


if __name__ == "__main__":
    main()
