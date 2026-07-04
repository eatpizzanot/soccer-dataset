"""Central configuration: paths + secret loading.

Secrets live OUTSIDE the repo (``pizzatipzhetzner.txt``) and are loaded on demand.
Secret *values* are never logged or printed by this module. Callers must treat returned
strings as sensitive.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

# --- Repository / working paths -------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_DIR = REPO_ROOT / "csv"
PARQUET_DIR = REPO_ROOT / "parquet"
BUILD_DIR = REPO_ROOT / "build"
STAGING_DB = BUILD_DIR / "staging.duckdb"
CURATED_DIR = BUILD_DIR / "curated"
HANDOFF_DIR = REPO_ROOT / "_handoff"
QA_OUT_DIR = BUILD_DIR / "qa"
SAMPLES_DIR = REPO_ROOT / "samples"
METADATA_DIR = REPO_ROOT / "metadata"
DOCS_DIR = REPO_ROOT / "docs"
# Cloudbet competition catalogue (tracked pipeline input); falls back to the scratch handoff dir.
CLOUDBET_CATALOG_CSV = METADATA_DIR / "cloudbet_catalog.csv"

for _d in (BUILD_DIR, CURATED_DIR, QA_OUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Secrets --------------------------------------------------------------------
SECRETS_FILE = Path(
    os.environ.get("PIZZATIPZ_SECRETS", r"C:\Users\eatpizzanot\Downloads\pizzatipzhetzner.txt")
)


def _normalize(label: str) -> str:
    return re.sub(r"[^a-z0-9]", "", label.lower())


@lru_cache(maxsize=1)
def _load_secrets() -> dict[str, str]:
    """Parse ``Label: value`` lines. Split on the first ':' only (values may contain ':')."""
    secrets: dict[str, str] = {}
    if not SECRETS_FILE.exists():
        return secrets
    for raw in SECRETS_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        label, _, value = line.partition(":")
        value = value.strip()
        if value:
            secrets[_normalize(label)] = value
    return secrets


def get_secret(label: str) -> str:
    key = _normalize(label)
    val = _load_secrets().get(key)
    if not val:
        raise KeyError(f"Secret '{label}' (normalized '{key}') not found in {SECRETS_FILE.name}")
    return val


def has_secret(label: str) -> bool:
    return _normalize(label) in _load_secrets()


# Named accessors (never print the return values)
def apifootball_key() -> str:
    return get_secret("API-Football")


def cloudbet_key() -> str:
    return get_secret("cloudbet")


def odds_api_key() -> str:
    return get_secret("ODDS-API")


def huggingface_token() -> str:
    return get_secret("huggingface")


# --- API-Football --------------------------------------------------------------
APIFOOTBALL_BASE = "https://v3.football.api-sports.io"
APIFOOTBALL_HEADER = "x-apisports-key"

# --- Canonical fixture key ------------------------------------------------------
FIXTURE_KEY = ("league_id", "date_utc", "home_team_id", "away_team_id")

# --- Postgres (source-of-truth on pundit-prod) ---------------------------------
PG_DB = "probodds_soccer"
PG_SSH_HOST = "pundit-prod"  # 77.42.38.219
EREMIE_SSH_HOST = "eremie-prod"  # 46.225.210.239
