"""Phase 4a - reconcile the league universe and produce the missing-league worklist.

Inputs:  build/apifootball/leagues.json (1,235 AF leagues + coverage), _handoff/cloudbet_catalog.csv
         (285 Cloudbet competitions), cln_leagues (our 144).
Outputs: build/curated/league_catalogue.parquet, build/qa/phase4_discovery.json,
         build/apifootball/ingest_worklist.json (Cloudbet-covered AF leagues missing from the set).
"""
from __future__ import annotations

import io
import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd  # noqa: E402

from pipeline import config as c  # noqa: E402
from pipeline import staging  # noqa: E402

COUNTRY_ALIAS = {
    "republic of ireland": "ireland",
    "republic of korea": "south korea",
    "international": "world",
    "international clubs": "world",
    "international youth": "world",
    "usa": "usa",
    "uae": "united arab emirates",
    "czechia": "czech republic",
    "bosnia and herzegovina": "bosnia",
    "bosnia herzegovina": "bosnia",
    "north macedonia": "macedonia",
    "chinese taipei": "taiwan",
}


def norm(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def cnorm(country: str | None) -> str:
    n = norm(country)
    return COUNTRY_ALIAS.get(n, n)


def load_af() -> pd.DataFrame:
    raw = json.loads((c.BUILD_DIR / "apifootball" / "leagues.json").read_text(encoding="utf-8"))
    rows = []
    for r in raw:
        lg, co, seasons = r["league"], r["country"], r.get("seasons", [])
        has_stats = any(
            (s.get("coverage", {}).get("fixtures", {}) or {}).get("statistics_fixtures")
            for s in seasons
        )
        years = [s.get("year") for s in seasons if s.get("year") is not None]
        rows.append({
            "af_league_id": lg["id"], "af_name": lg["name"], "af_type": lg["type"],
            "af_country": co["name"], "af_has_stats": has_stats,
            "min_season": min(years) if years else None, "max_season": max(years) if years else None,
            "nname": norm(lg["name"]), "ccountry": cnorm(co["name"]),
        })
    return pd.DataFrame(rows)


EXCLUDE_RE = re.compile(r"\b(u1[5-9]|u2[0-3]|youth|women|womens|reserve|reserves|amateur)\b|women", re.I)


def match_cloudbet(cb: pd.DataFrame, af: pd.DataFrame) -> pd.DataFrame:
    by_ck_name: dict[tuple, list] = {}
    by_name: dict[str, list] = {}
    for _, a in af.iterrows():
        by_ck_name.setdefault((a.ccountry, a.nname), []).append(a)
        by_name.setdefault(a.nname, []).append(a)

    def tokens(s: str) -> set:
        return set(t for t in s.split() if t not in {"the", "de", "of", "1", "league", "liga", "division"})

    out = []
    for _, r in cb.iterrows():
        cn, cc = norm(r["name"]), cnorm(r["category_name"])
        af_id, tier, af_name = None, "unmapped", None
        if EXCLUDE_RE.search(r["name"] or ""):
            tier = "excluded_scope"
        else:
            cands = by_ck_name.get((cc, cn))
            if cands and len(cands) == 1:
                af_id, tier, af_name = cands[0].af_league_id, "exact_country_name", cands[0].af_name
            elif cands:
                leaguey = [x for x in cands if x.af_type == "League"] or cands
                af_id, tier, af_name = leaguey[0].af_league_id, "exact_country_name_multi", leaguey[0].af_name
            else:
                nm = by_name.get(cn)
                same_c = [x for x in (nm or []) if x.ccountry == cc]
                if same_c:
                    af_id, tier, af_name = same_c[0].af_league_id, "name_country", same_c[0].af_name
                else:
                    # token-subset match within same country (handles "Brasileiro Serie A" vs "Serie A")
                    pool = af[af.ccountry == cc]
                    ctok = tokens(cn)
                    best, bestscore, besttier = None, 0.0, None
                    for _, a in pool.iterrows():
                        atok = tokens(a.nname)
                        if not ctok or not atok:
                            continue
                        inter = ctok & atok
                        if inter and (ctok <= atok or atok <= ctok):
                            score = len(inter) / max(len(ctok), len(atok)) + (0.1 if a.af_type == "League" else 0)
                            if score > bestscore:
                                best, bestscore, besttier = a, score, "token_subset"
                    if best is None:
                        for _, a in pool.iterrows():
                            ratio = SequenceMatcher(None, cn, a.nname).ratio()
                            if ratio > bestscore:
                                best, bestscore, besttier = a, ratio, f"fuzzy_{ratio:.2f}"
                        if bestscore < 0.6:
                            best = None
                    if best is not None:
                        af_id, tier, af_name = best.af_league_id, besttier, best.af_name
        out.append({
            "cloudbet_key": r["key"], "cloudbet_name": r["name"], "cloudbet_country": r["category_name"],
            "cb_sources": r.get("sources"), "af_league_id": af_id, "af_name": af_name, "match_tier": tier,
        })
    return pd.DataFrame(out)


def main() -> None:
    con = staging.connect()
    af = load_af()
    cb_path = c.CLOUDBET_CATALOG_CSV if c.CLOUDBET_CATALOG_CSV.exists() else (c.HANDOFF_DIR / "cloudbet_catalog.csv")
    cb = pd.read_csv(cb_path)
    ours = con.execute("SELECT id AS dataset_league_id, \"name\", country, api_football_id FROM cln_leagues").df()

    cbmap = match_cloudbet(cb, af)
    mapped = cbmap[cbmap.af_league_id.notna()].copy()
    mapped["af_league_id"] = mapped["af_league_id"].astype("int64")

    # our dataset leagues by api id
    ours_ids = set(int(x) for x in ours.api_football_id.dropna())

    # Build league catalogue: one row per AF league, with flags
    af2 = af.copy()
    af2["in_dataset"] = af2.af_league_id.isin(ours_ids)
    cb_by_af = mapped.groupby("af_league_id").agg(
        cloudbet_key=("cloudbet_key", "first"), cloudbet_name=("cloudbet_name", "first"),
        cloudbet_matches=("cloudbet_key", "count")).reset_index()
    cat = af2.merge(cb_by_af, on="af_league_id", how="left")
    cat["in_cloudbet"] = cat.cloudbet_key.notna()
    cat = cat.merge(ours[["api_football_id", "dataset_league_id"]],
                    left_on="af_league_id", right_on="api_football_id", how="left")

    # missing = in cloudbet, mapped, but NOT in our dataset
    missing = cat[(cat.in_cloudbet) & (~cat.in_dataset)].copy()
    worklist = missing[["af_league_id", "af_name", "af_type", "af_has_stats",
                        "min_season", "max_season", "cloudbet_key", "cloudbet_name"]].assign(
        af_country=missing["af_country"]).sort_values("af_country")

    # per-league history coverage: seasons present in the dataset vs seasons API-Football offers
    pres = con.execute("""
      SELECT l.api_football_id AS af_league_id,
             count(DISTINCT f.calendar_year) AS present_years, min(f.calendar_year) AS min_year
      FROM cln_fixtures f JOIN cln_leagues l ON l.id = f.league_id
      WHERE l.api_football_id IS NOT NULL GROUP BY 1
    """).df()
    cat = cat.merge(pres, on="af_league_id", how="left")
    cat["avail_years"] = (cat.max_season - cat.min_season + 1).clip(lower=1)

    def _hist(r):
        if not r.in_dataset:
            return "not_in_dataset"
        if pd.isna(r.present_years):
            return "unknown"
        frac = r.present_years / max(r.avail_years, 1)
        if frac >= 0.7:
            return "full"
        if not pd.isna(r.min_year) and r.min_year >= 2023:
            return "recent_only"
        return "partial"

    cat["history_status"] = cat.apply(_hist, axis=1)

    # persist
    out_cat = cat[["af_league_id", "af_name", "af_country", "af_type", "af_has_stats",
                   "min_season", "max_season", "in_dataset", "dataset_league_id",
                   "in_cloudbet", "cloudbet_key", "cloudbet_name", "present_years",
                   "avail_years", "history_status"]]
    out_cat.to_parquet(c.CURATED_DIR / "league_catalogue.parquet", index=False)
    worklist.to_json(c.BUILD_DIR / "apifootball" / "ingest_worklist.json", orient="records", indent=2)
    cbmap.to_parquet(c.BUILD_DIR / "apifootball" / "cloudbet_mapping.parquet", index=False)

    rep = {
        "af_leagues_total": int(len(af)),
        "cloudbet_competitions": int(len(cb)),
        "cloudbet_mapped": int(mapped.shape[0]),
        "cloudbet_unmapped": int((cbmap.match_tier == "unmapped").sum()),
        "cloudbet_excluded_scope": int((cbmap.match_tier == "excluded_scope").sum()),
        "cloudbet_mapped_distinct_af": int(mapped.af_league_id.nunique()),
        "cloudbet_already_in_dataset": int(cat[(cat.in_cloudbet) & (cat.in_dataset)].shape[0]),
        "cloudbet_missing_from_dataset": int(worklist.shape[0]),
        "our_leagues": int(len(ours)),
        "match_tiers": cbmap.match_tier.apply(lambda t: t.split("_")[0] if t.startswith("fuzzy") else t).value_counts().to_dict(),
    }
    (c.QA_OUT_DIR / "phase4_discovery.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")

    print("===== PHASE 4a LEAGUE RECONCILIATION =====")
    for k, v in rep.items():
        print(f"  {k:<34} {v}")
    print("\nGenuinely unmapped Cloudbet competitions (not excluded-scope):")
    for _, r in cbmap[cbmap.match_tier == "unmapped"].iterrows():
        print(f"  - {r.cloudbet_country:<20} {r.cloudbet_name}")
    con.close()


if __name__ == "__main__":
    main()
