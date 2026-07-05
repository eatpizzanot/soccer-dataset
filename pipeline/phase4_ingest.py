"""Phase 4b - ingest fixtures (and teams) for leagues/seasons from API-Football.

Fixtures-first strategy: one cheap call per (league, season) yields goals/status/teams -> BTTS
labels + coverage, and discovers new teams. Per-fixture stats/lineups/players are a separate,
more expensive backfill (phase4_ingest_stats). Results are appended idempotently to
``raw_ingest_*`` tables in build/staging.duckdb (dedup by api id), so re-runs are safe.
"""
from __future__ import annotations

import concurrent.futures
import io
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests  # noqa: E402

from pipeline import config as c  # noqa: E402
from pipeline import staging  # noqa: E402
from pipeline.apifootball import ApiFootball  # noqa: E402

DDL_FIX = """
CREATE TABLE IF NOT EXISTS raw_ingest_fixtures (
  api_football_id BIGINT PRIMARY KEY, date_utc TIMESTAMP, status VARCHAR,
  league_af_id BIGINT, league_name VARCHAR, country VARCHAR, season INTEGER, round VARCHAR,
  home_team_af_id BIGINT, home_team_name VARCHAR, away_team_af_id BIGINT, away_team_name VARCHAR,
  goals_home INTEGER, goals_away INTEGER, ht_home INTEGER, ht_away INTEGER,
  referee_name VARCHAR, ingested_at TIMESTAMP
)"""
DDL_TEAM = """
CREATE TABLE IF NOT EXISTS raw_ingest_teams (
  api_football_id BIGINT PRIMARY KEY, name VARCHAR, country VARCHAR, ingested_at TIMESTAMP
)"""


def _parse_dt(s: str) -> str | None:
    # API returns e.g. 2024-08-16T19:00:00+00:00 -> store UTC-naive
    if not s:
        return None
    return s.replace("T", " ")[:19]


def ingest(pairs: list[tuple[int, int]], label: str = "") -> dict:
    """pairs: list of (af_league_id, season)."""
    con = staging.connect()
    con.execute(DDL_FIX)
    con.execute(DDL_TEAM)
    af = ApiFootball()
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    n_fix = errors = 0
    for i, (lid, season) in enumerate(pairs, 1):
        try:
            resp = af.get("fixtures", {"league": lid, "season": season})
        except Exception as e:  # a bad league-season must not abort the whole backfill
            errors += 1
            print(f"  [{label}] league {lid} season {season} error: {str(e)[:70]}", flush=True)
            continue
        frows, trows = [], {}
        for it in resp:
            fx, lg, tm, gl = it["fixture"], it["league"], it["teams"], it["goals"]
            sc = it.get("score", {}) or {}
            ht = (sc.get("halftime") or {})
            frows.append((
                fx["id"], _parse_dt(fx.get("date")), (fx.get("status") or {}).get("short"),
                lg["id"], lg.get("name"), lg.get("country"), lg.get("season"), lg.get("round"),
                tm["home"]["id"], tm["home"]["name"], tm["away"]["id"], tm["away"]["name"],
                gl.get("home"), gl.get("away"), ht.get("home"), ht.get("away"),
                fx.get("referee"), now,
            ))
            for side in ("home", "away"):
                t = tm[side]
                trows[t["id"]] = (t["id"], t["name"], lg.get("country"), now)
        if frows:
            con.executemany(
                "INSERT OR REPLACE INTO raw_ingest_fixtures VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", frows)
            con.executemany("INSERT OR REPLACE INTO raw_ingest_teams VALUES (?,?,?,?)", list(trows.values()))
            n_fix += len(frows)
        if i % 20 == 0 or i == len(pairs):
            print(f"  [{label}] {i}/{len(pairs)} league-seasons, {n_fix} fixtures, {errors} errors, {af.request_count} api calls", flush=True)
    total = con.execute("SELECT count(*) FROM raw_ingest_fixtures").fetchone()[0]
    con.close()
    return {"pairs": len(pairs), "fixtures_ingested_this_run": n_fix, "errors": errors,
            "raw_ingest_fixtures_total": total, "api_calls": af.request_count}


# ---------------------------------------------------------------- stats + lineups
DDL_MS = """
CREATE TABLE IF NOT EXISTS raw_ingest_match_stats (
  api_football_id BIGINT PRIMARY KEY,
  home_shots_total INTEGER, away_shots_total INTEGER,
  home_shots_on_goal INTEGER, away_shots_on_goal INTEGER,
  home_shots_inside_box INTEGER, away_shots_inside_box INTEGER,
  home_shots_outside_box INTEGER, away_shots_outside_box INTEGER,
  home_blocked_shots INTEGER, away_blocked_shots INTEGER,
  home_corners INTEGER, away_corners INTEGER,
  home_yellow_cards INTEGER, away_yellow_cards INTEGER,
  home_red_cards INTEGER, away_red_cards INTEGER,
  home_possession INTEGER, away_possession INTEGER,
  home_fouls INTEGER, away_fouls INTEGER,
  home_offsides INTEGER, away_offsides INTEGER,
  home_pass_accuracy INTEGER, away_pass_accuracy INTEGER,
  home_xg DOUBLE, away_xg DOUBLE, stats_fetched_at TIMESTAMP
)"""
DDL_LU = """
CREATE TABLE IF NOT EXISTS raw_ingest_lineups (
  api_football_id BIGINT, team_af_id BIGINT, team_name VARCHAR,
  coach_name VARCHAR, coach_api_id BIGINT, formation VARCHAR,
  PRIMARY KEY (api_football_id, team_af_id)
)"""
DDL_DONE = "CREATE TABLE IF NOT EXISTS raw_ingest_fx_done (api_football_id BIGINT PRIMARY KEY, done_at TIMESTAMP)"

_STAT_MAP = {
    "Total Shots": "shots_total", "Shots on Goal": "shots_on_goal",
    "Shots insidebox": "shots_inside_box", "Shots outsidebox": "shots_outside_box",
    "Blocked Shots": "blocked_shots", "Corner Kicks": "corners",
    "Yellow Cards": "yellow_cards", "Red Cards": "red_cards",
    "Ball Possession": "possession", "Fouls": "fouls", "Offsides": "offsides",
    "Passes %": "pass_accuracy", "expected_goals": "xg",
}
_MS_FIELDS = ["shots_total", "shots_on_goal", "shots_inside_box", "shots_outside_box",
              "blocked_shots", "corners", "yellow_cards", "red_cards", "possession",
              "fouls", "offsides", "pass_accuracy", "xg"]


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip().rstrip("%")
    try:
        f = float(s)
        return int(f) if f == int(f) else f
    except ValueError:
        return None


def _team_stats(entry) -> dict:
    d = {}
    for s in entry.get("statistics", []):
        key = _STAT_MAP.get(s.get("type"))
        if key:
            d[key] = _num(s.get("value"))
    return d


def ingest_stats_lineups(fixture_ids: list[int], label: str = "", commit_every: int = 200) -> dict:
    """Fetch /fixtures/statistics + /fixtures/lineups per fixture. Resumable via raw_ingest_fx_done."""
    con = staging.connect()
    for ddl in (DDL_MS, DDL_LU, DDL_DONE):
        con.execute(ddl)
    done = {r[0] for r in con.execute("SELECT api_football_id FROM raw_ingest_fx_done").fetchall()}
    todo = [f for f in dict.fromkeys(fixture_ids) if f not in done]
    ha = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT api_football_id, home_team_af_id, away_team_af_id FROM raw_ingest_fixtures").fetchall()}
    af = ApiFootball()
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    got_ms = got_lu = 0
    for i, fid in enumerate(todo, 1):
        try:
            st = af.get("fixtures/statistics", {"fixture": fid})
            lu = af.get("fixtures/lineups", {"fixture": fid})
        except Exception as e:  # network/API error -> leave un-done for a later pass
            print(f"  [{label}] fixture {fid} error: {str(e)[:60]}", flush=True)
            continue
        home_af, away_af = ha.get(fid, (None, None))
        if st:
            per = {}
            for entry in st:
                per[entry["team"]["id"]] = _team_stats(entry)
            hs = per.get(home_af, {})
            as_ = per.get(away_af, {})
            if not hs and len(st) == 2:  # fall back to positional (home first)
                hs, as_ = _team_stats(st[0]), _team_stats(st[1])
            vals = [fid]
            for f in _MS_FIELDS:
                vals.append(hs.get(f)); vals.append(as_.get(f))
            vals.append(now)
            con.execute("INSERT OR REPLACE INTO raw_ingest_match_stats VALUES (" + ",".join(["?"] * len(vals)) + ")", vals)
            got_ms += 1
        for entry in lu or []:
            t = entry["team"]; coach = entry.get("coach") or {}
            con.execute("INSERT OR REPLACE INTO raw_ingest_lineups VALUES (?,?,?,?,?,?)",
                        [fid, t["id"], t.get("name"), coach.get("name"), coach.get("id"), entry.get("formation")])
            got_lu += 1
        con.execute("INSERT OR REPLACE INTO raw_ingest_fx_done VALUES (?, ?)", [fid, now])
        if i % commit_every == 0 or i == len(todo):
            print(f"  [{label}] {i}/{len(todo)} fixtures; ms={got_ms} lu={got_lu} calls={af.request_count}", flush=True)
    return {"todo": len(todo), "match_stats": got_ms, "lineups_rows": got_lu, "api_calls": af.request_count}


# ---------------------------------------------------------------- parallel stats fetch
class _RateLimiter:
    def __init__(self, rpm: int) -> None:
        self.interval = 60.0 / rpm
        self.lock = threading.Lock()
        self.next = 0.0

    def acquire(self) -> None:
        with self.lock:
            now = time.time()
            start = max(now, self.next)
            self.next = start + self.interval
        delay = start - time.time()
        if delay > 0:
            time.sleep(delay)


_tls = threading.local()


def _session() -> requests.Session:
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        s.headers[c.APIFOOTBALL_HEADER] = c.apifootball_key()
        _tls.s = s
    return s


def _get(endpoint: str, params: dict, rl: _RateLimiter, tries: int = 4):
    for a in range(tries):
        rl.acquire()
        try:
            r = _session().get(f"{c.APIFOOTBALL_BASE}/{endpoint}", params=params, timeout=40)
            if r.status_code == 429:
                time.sleep(2 * (a + 1))
                continue
            r.raise_for_status()
            return r.json().get("response", []) or []
        except requests.RequestException:
            time.sleep(1.5 * (a + 1))
    return None


def _fetch_one(fid: int, ha: dict, rl: _RateLimiter):
    st = _get("fixtures/statistics", {"fixture": fid}, rl)
    lu = _get("fixtures/lineups", {"fixture": fid}, rl)
    if st is None and lu is None:
        return fid, None, [], False
    ms = None
    if st:
        per = {e["team"]["id"]: _team_stats(e) for e in st}
        home_af, away_af = ha.get(fid, (None, None))
        hs, as_ = per.get(home_af, {}), per.get(away_af, {})
        if not hs and len(st) == 2:
            hs, as_ = _team_stats(st[0]), _team_stats(st[1])
        ms = [fid]
        for f in _MS_FIELDS:
            ms.append(hs.get(f)); ms.append(as_.get(f))
    lus = []
    for e in lu or []:
        t = e["team"]; co = e.get("coach") or {}
        lus.append([fid, t["id"], t.get("name"), co.get("name"), co.get("id"), e.get("formation")])
    return fid, ms, lus, True


def ingest_stats_lineups_parallel(fixture_ids: list[int], workers: int = 12, rpm: int = 850,
                                  label: str = "", commit_every: int = 500) -> dict:
    con = staging.connect()
    for ddl in (DDL_MS, DDL_LU, DDL_DONE):
        con.execute(ddl)
    done = {r[0] for r in con.execute("SELECT api_football_id FROM raw_ingest_fx_done").fetchall()}
    todo = [f for f in dict.fromkeys(fixture_ids) if f not in done]
    ha = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT api_football_id, home_team_af_id, away_team_af_id FROM raw_ingest_fixtures").fetchall()}
    rl = _RateLimiter(rpm)
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    got_ms = got_lu = processed = errors = 0
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_fetch_one, fid, ha, rl) for fid in todo]
        for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            fid, ms, lus, ok = fut.result()
            if not ok:
                errors += 1
                continue
            if ms is not None:
                con.execute("INSERT OR REPLACE INTO raw_ingest_match_stats VALUES (" + ",".join(["?"] * (len(ms) + 1)) + ")", ms + [now])
                got_ms += 1
            for lr in lus:
                con.execute("INSERT OR REPLACE INTO raw_ingest_lineups VALUES (?,?,?,?,?,?)", lr)
                got_lu += 1
            con.execute("INSERT OR REPLACE INTO raw_ingest_fx_done VALUES (?, ?)", [fid, now])
            processed += 1
            if processed % commit_every == 0 or i == len(todo):
                rate = i / max(time.time() - t0, 1)
                print(f"  [{label}] {i}/{len(todo)} ms={got_ms} lu={got_lu} err={errors} "
                      f"{rate:.1f} fx/s", flush=True)
    con.close()
    return {"todo": len(todo), "match_stats": got_ms, "lineups_rows": got_lu, "errors": errors}


if __name__ == "__main__":
    # smoke test: EPL 2024 (af league 39)
    import json
    print(json.dumps(ingest([(39, 2024)], label="smoke"), indent=2))
