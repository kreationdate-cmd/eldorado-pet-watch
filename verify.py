"""
Health check for eldorado-pet-watch.

Usage:  python verify.py https://github.com/<USERNAME>/eldorado-pet-watch
   or:  python verify.py <path to a local clone>

Every scraper run commits the data/ folder (even failed runs commit
status.json), so the commit history shows when the workflow ran and
the data files show whether it worked. No GitHub login needed.
"""

import csv
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
results = []


def check(level, name, detail):
    results.append((level, name, detail))


def git(repo, *args):
    out = subprocess.run(["git", "-C", str(repo), *args],
                         capture_output=True, text=True)
    return out.stdout.strip()


def get_repo(target):
    path = Path(target)
    if path.exists():
        return path
    tmp = Path(tempfile.mkdtemp()) / "repo"
    r = subprocess.run(["git", "clone", "--quiet", target, str(tmp)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FAIL  clone: {r.stderr.strip() or 'could not clone'}")
        print("      Check the URL, and that the repo is public.")
        sys.exit(2)
    return tmp


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    repo = get_repo(sys.argv[1])
    now = datetime.now(timezone.utc)

    # 1. Files in the right places
    needed = ["scraper.py", "pets.txt", "requirements.txt",
              ".github/workflows/scrape.yml"]
    missing = [f for f in needed if not (repo / f).exists()]
    if missing:
        check(FAIL, "files", "missing: " + ", ".join(missing)
              + " (the workflow file must be at .github/workflows/scrape.yml)")
    else:
        check(PASS, "files", "all files in place")

    data = repo / "data"
    if not data.exists():
        check(FAIL, "workflow ran", "no data/ folder yet. Either the workflow has "
              "not run (Actions tab > Run workflow) or it could not push "
              "(Settings > Actions > General > Read and write permissions)")
        return report()

    # 2. Run history from commits that touched data/
    log = git(repo, "log", "--format=%cI", "--", "data/")
    times = [datetime.fromisoformat(t) for t in log.splitlines() if t]
    check(PASS, "workflow ran", f"{len(times)} data commits, first {times[-1]:%Y-%m-%d %H:%M} UTC")

    age_min = (now - times[0]).total_seconds() / 60
    if age_min <= 75:
        check(PASS, "fresh", f"last run {age_min:.0f} min ago")
    elif age_min <= 180:
        check(WARN, "fresh", f"last run {age_min:.0f} min ago (GitHub can run late)")
    else:
        check(FAIL, "fresh", f"last run {age_min / 60:.1f} h ago. Schedule may be off: "
              "Actions tab, check the workflow is enabled")

    day = [t for t in times if (now - t).total_seconds() <= 86400]
    gaps = [(b, a) for a, b in zip(day, day[1:]) if (a - b).total_seconds() > 5400]
    if len(times) < 3:
        check(WARN, "hourly", "too few runs yet to judge the schedule")
    elif gaps:
        detail = "; ".join(f"{b:%H:%M}->{a:%H:%M}" for b, a in gaps[:5])
        check(WARN, "hourly", f"{len(day)} runs in 24h, gaps over 90 min (UTC): {detail}")
    else:
        check(PASS, "hourly", f"{len(day)} runs in last 24h, no gaps over 90 min")

    # 3. Did the last run work?
    status = json.loads((data / "status.json").read_text()) if (data / "status.json").exists() else {}
    if status.get("ok"):
        check(PASS, "last run", f"ok at {status.get('time_utc')}")
    elif status:
        check(FAIL, "last run", f"error: {status.get('error')} "
              f"({status.get('fail_streak', 1)} failed runs in a row). "
              "HTTP 403/429 or 'not JSON' means Eldorado is blocking GitHub's servers")
    else:
        check(FAIL, "last run", "no status.json")

    # 4. Is the data sane?
    latest_path = data / "latest.json"
    if latest_path.exists():
        latest = json.loads(latest_path.read_text())
        total, pets = latest.get("total_listings", 0), latest.get("pet_listings", 0)
        groups = latest.get("summary", [])
        unknown = latest.get("unknown_pet_titles", [])
        deals = latest.get("deals", [])
        check(PASS if total >= 300 else WARN, "listings",
              f"{total} listings (967 on 2026-10-22)"
              + ("" if total >= 300 else ". Far fewer than expected; API may have changed"))
        share = pets / total if total else 0
        check(PASS if share >= 0.2 else WARN, "pets matched",
              f"{pets} pet listings ({share:.0%}) in {len(groups)} pet+variant groups")
        check(PASS if len(unknown) <= 15 else WARN, "unknown titles",
              f"{len(unknown)} pet-like titles matched no name in pets.txt")
        base = lambda d: d.get("baseline_usd", d.get("median_of_others"))
        bad = [d for d in deals if not (0 < d["price_usd"] < base(d))]
        check(FAIL if bad else PASS, "deal math",
              f"{len(deals)} deals flagged" + (f", {len(bad)} with impossible numbers" if bad else ", numbers consistent"))
        latest_dt = datetime.fromisoformat(latest["time_utc"])
        if status.get("ok") and abs((latest_dt - datetime.fromisoformat(status["time_utc"])).total_seconds()) > 60:
            check(FAIL, "files agree", "latest.json and status.json are from different runs")
    elif status.get("ok"):
        check(FAIL, "listings", "status says ok but there is no latest.json")

    hist = data / "history.csv"
    if hist.exists():
        with hist.open() as f:
            rows = list(csv.DictReader(f))
        runs = len({r["time_utc"] for r in rows})
        check(PASS, "history", f"{len(rows)} rows across {runs} successful runs")

    return report()


def report():
    for level, name, detail in results:
        print(f"{level:4}  {name}: {detail}")
    worst = FAIL if any(r[0] == FAIL for r in results) else WARN if any(r[0] == WARN for r in results) else PASS
    print(f"\nOVERALL: {worst}")
    return 1 if worst == FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
