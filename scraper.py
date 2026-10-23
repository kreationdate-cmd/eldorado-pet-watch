"""
Eldorado Tap Simulator REBORN pet watcher.

Runs once per hour on GitHub Actions. Each run:
  1. Downloads every Tap Simulator REBORN item listing from Eldorado's
     public listings API (the same JSON the website itself loads).
  2. Works out which pet (and variant: Golden, Diamond, Rainbow, Shiny)
     each listing is, using the names in pets.txt.
  3. Compares each listing's price to the median price of the other
     listings for the same pet + variant.
  4. Writes the results into the data/ folder, which the workflow
     commits back to the repo so Claude can read them.

Files written:
  data/latest.json   every pet listing from this run, plus deals
  data/history.csv   one row per pet+variant per run (min, median, count)
  data/seen.json     when each listing was first seen (to spot new ones)
  data/status.json   whether the run worked, and if not, why
"""

import csv
import json
import re
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------- settings

API_URL = "https://www.eldorado.gg/api/v1/item-management/offers"
GAME_ID = "350"            # Tap Simulator REBORN on Eldorado
PAGE_SIZE = 50             # the API accepts up to 50 per page
PAUSE_SECONDS = 2          # wait between pages, to be gentle on the site
DEAL_THRESHOLD = 0.30      # 30% below the median counts as a deal
MIN_COMPARABLES = 3        # need at least 3 other listings to trust a median
SEEN_KEEP_DAYS = 7         # forget listings not seen for this many days

ROOT = Path(__file__).parent
DATA = ROOT / "data"
PETS_FILE = ROOT / "pets.txt"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.eldorado.gg/tap-simulator-shop/i/350",
}

# Words in a title that mean a variant. Order matters only for display.
VARIANT_WORDS = {
    "shiny": "Shiny",
    "golden": "Golden",
    "gold": "Golden",
    "diamond": "Diamond",
    "rainbow": "Rainbow",
}


# ---------------------------------------------------------------- helpers

def now_utc():
    return datetime.now(timezone.utc)


def clean(text):
    """Lowercase, turn punctuation into spaces, collapse spaces."""
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def load_pet_names():
    """Read pets.txt: one pet name per line, # starts a comment."""
    names = []
    for line in PETS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            names.append(line)
    # Longest names first, so "Void Overseer" wins over a shorter match.
    return sorted(names, key=len, reverse=True)


def identify(title, pet_names):
    """Return (pet, variant) for a listing title, or (None, None)."""
    t = " " + clean(title) + " "
    pet = None
    for name in pet_names:
        if " " + clean(name) + " " in t:
            pet = name
            break
    if pet is None:
        return None, None
    found = []
    for word, label in VARIANT_WORDS.items():
        if " " + word + " " in t and label not in found:
            found.append(label)
    # Keep a fixed order, e.g. "Shiny Rainbow", so the same variant
    # always gets the same name.
    order = ["Shiny", "Golden", "Diamond", "Rainbow"]
    variant = " ".join(v for v in order if v in found) or "Normal"
    return pet, variant


def looks_like_unknown_pet(title):
    """A title that sounds like a pet but matched no name in pets.txt."""
    t = clean(title)
    return bool(re.search(r"\bsecret\b|\b1 in \d|\bmythic", t))


# ---------------------------------------------------------------- download

def fetch_page(session, page):
    params = {
        "gameId": GAME_ID,
        "category": "CustomItem",
        "pageIndex": page,
        "pageSize": PAGE_SIZE,
        "useMinPurchasePrice": "false",
        "includeDeliveryMedians": "true",
    }
    resp = session.get(API_URL, params=params, headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"page {page}: HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError:
        # Usually means a block page (HTML) came back instead of JSON.
        raise RuntimeError(f"page {page}: response was not JSON")


def fetch_all():
    session = requests.Session()
    offers = []
    page = 1
    while True:
        data = fetch_page(session, page)
        offers.extend(data.get("results", []))
        total_pages = data.get("totalPages", 1)
        if page >= total_pages:
            break
        page += 1
        time.sleep(PAUSE_SECONDS)
    return offers


def flatten(raw):
    """Pick out the fields we care about from one API result."""
    offer = raw.get("offer") or {}
    user = raw.get("user") or {}
    info = raw.get("userOrderInfo") or {}
    price = (offer.get("pricePerUnitInUSD") or {}).get("amount")
    if price is None:
        price = (offer.get("pricePerUnit") or {}).get("amount")
    return {
        "id": offer.get("id"),
        "title": (offer.get("offerTitle") or "").strip(),
        "price_usd": price,
        "stock": offer.get("quantity"),
        "seller": user.get("username"),
        "seller_feedback_pct": round(info["feedbackScore"], 1)
        if info.get("feedbackScore") is not None else None,
        "seller_reviews": info.get("ratingCount"),
        "url": f"https://www.eldorado.gg/tap-simulator-shop/oi/{offer.get('id')}",
    }


# ---------------------------------------------------------------- analysis

def analyse(listings, pet_names, seen, run_time):
    pets, unknown = [], []
    for item in listings:
        if not item["id"] or item["price_usd"] is None:
            continue
        pet, variant = identify(item["title"], pet_names)
        if pet is None:
            if looks_like_unknown_pet(item["title"]):
                unknown.append(item)
            continue
        item["pet"], item["variant"] = pet, variant
        item["key"] = f"{pet} | {variant}"
        pets.append(item)

    # Group listings by pet + variant.
    groups = {}
    for item in pets:
        groups.setdefault(item["key"], []).append(item)

    # New-listing / price-drop tracking.
    stamp = run_time.isoformat(timespec="seconds")
    for item in pets:
        prev = seen.get(item["id"])
        item["is_new"] = prev is None
        item["price_dropped"] = bool(prev and item["price_usd"] < prev["last_price"])
        item["first_seen"] = prev["first_seen"] if prev else stamp
        seen[item["id"]] = {
            "first_seen": item["first_seen"],
            "last_seen": stamp,
            "last_price": item["price_usd"],
        }

    deals, summary = [], []
    for key, items in sorted(groups.items()):
        prices = [i["price_usd"] for i in items]
        summary.append({
            "key": key,
            "count": len(items),
            "min": min(prices),
            "median": round(statistics.median(prices), 2),
        })
        for item in items:
            others = [i["price_usd"] for i in items if i is not item]
            if len(others) < MIN_COMPARABLES:
                continue
            median = statistics.median(others)
            if median <= 0:
                continue
            discount = 1 - item["price_usd"] / median
            if discount >= DEAL_THRESHOLD:
                deal = dict(item)
                deal["median_of_others"] = round(median, 2)
                deal["discount_pct"] = round(discount * 100, 1)
                deal["comparables"] = len(others)
                deals.append(deal)

    deals.sort(key=lambda d: d["discount_pct"], reverse=True)
    return pets, unknown, deals, summary


def prune_seen(seen, run_time):
    cutoff = run_time - timedelta(days=SEEN_KEEP_DAYS)
    return {
        k: v for k, v in seen.items()
        if datetime.fromisoformat(v["last_seen"]) >= cutoff
    }


# ---------------------------------------------------------------- files

def read_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


def append_history(summary, run_time):
    path = DATA / "history.csv"
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["time_utc", "pet_variant", "count", "min_usd", "median_usd"])
        stamp = run_time.isoformat(timespec="seconds")
        for row in summary:
            w.writerow([stamp, row["key"], row["count"], row["min"], row["median"]])


# ---------------------------------------------------------------- main

def main():
    DATA.mkdir(exist_ok=True)
    run_time = now_utc()
    stamp = run_time.isoformat(timespec="seconds")

    try:
        raw = fetch_all()
    except Exception as err:  # network error, block page, bad status...
        old = read_json(DATA / "status.json", {})
        streak = old.get("fail_streak", 0) + 1 if not old.get("ok", True) else 1
        write_json(DATA / "status.json", {
            "ok": False, "time_utc": stamp, "error": str(err),
            "fail_streak": streak,   # failed runs in a row
        })
        print(f"FAILED: {err}")
        return 1

    listings = [flatten(r) for r in raw]
    pet_names = load_pet_names()
    seen = read_json(DATA / "seen.json", {})

    pets, unknown, deals, summary = analyse(listings, pet_names, seen, run_time)

    write_json(DATA / "latest.json", {
        "time_utc": stamp,
        "total_listings": len(listings),
        "pet_listings": len(pets),
        "deal_threshold_pct": int(DEAL_THRESHOLD * 100),
        "deals": deals,
        "unknown_pet_titles": [
            {"title": u["title"], "price_usd": u["price_usd"], "url": u["url"]}
            for u in unknown
        ],
        "summary": summary,
        "pets": pets,
    })
    write_json(DATA / "seen.json", prune_seen(seen, run_time))
    append_history(summary, run_time)
    write_json(DATA / "status.json", {
        "ok": True, "time_utc": stamp,
        "total_listings": len(listings), "pet_listings": len(pets),
        "deals": len(deals), "new_deals": sum(d["is_new"] or d["price_dropped"] for d in deals),
    })
    print(f"OK: {len(listings)} listings, {len(pets)} pets, {len(deals)} deals")
    return 0


if __name__ == "__main__":
    sys.exit(main())
