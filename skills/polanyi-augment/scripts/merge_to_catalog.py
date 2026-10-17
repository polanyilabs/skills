#!/usr/bin/env python3
"""Map Polanyi synthetic events onto the user's own catalog IDs and report coverage.

Matching order for each event that names an item:
  1. the site's ID equals a catalog ID (case-insensitive)
  2. a catalog ID or catalog URL path appears in the event's product URL
  3. the product name matches a catalog name (price breaks ties)
Anything that does not match is dropped and counted, never guessed.

Example:
  python merge_to_catalog.py --events runs/x --catalog items.csv --id-col product_id \
      --name-col title --price-col price --interactions events.parquet --item-col item_id \
      --user-col user_id --event-col event --out augmented.parquet
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix in (".jsonl", ".json"):
        return pd.read_json(path, lines=path.suffix == ".jsonl")
    return pd.read_csv(path)


def load_events(paths: list[Path]) -> pd.DataFrame:
    files: list[Path] = []
    for p in paths:
        files += sorted(p.rglob("recsys_events.jsonl")) if p.is_dir() else [p]
    if not files:
        sys.exit("No recsys_events.jsonl found under --events.")
    return pd.concat([pd.read_json(f, lines=True) for f in files], ignore_index=True)


def as_id(value: object) -> str | None:
    """One string form for item IDs: pandas turns numeric IDs into floats when a column has gaps (1001 -> 1001.0)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def norm(text: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def url_path(text: object) -> str:
    return urlparse(str(text)).path.rstrip("/").lower() if text else ""


def event_url(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("url") or payload.get("product_url") or payload.get("source_url") or "")


def event_name(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("name") or payload.get("title") or payload.get("product_name") or "")


def event_price(payload: object) -> float | None:
    if not isinstance(payload, dict):
        return None
    p = payload.get("price_usd") or payload.get("selected_price_usd")
    return float(p) if isinstance(p, (int, float)) else None


def build_matcher(catalog: pd.DataFrame, id_col: str, url_col: str | None, name_col: str | None, price_col: str | None):
    ids = {i.lower(): i for i in map(as_id, catalog[id_col]) if i}
    paths = {url_path(u): as_id(i) for i, u in zip(catalog[id_col], catalog[url_col])} if url_col else {}
    names: dict[str, list[tuple[str, float | None]]] = {}
    if name_col:
        prices = catalog[price_col] if price_col else [None] * len(catalog)
        for i, n, p in zip(catalog[id_col], catalog[name_col], prices):
            names.setdefault(norm(n), []).append((as_id(i), float(p) if pd.notna(p) else None))

    def match(site_id: object, payload: object) -> tuple[str | None, str]:
        sid = as_id(site_id)
        if sid and sid.lower() in ids:
            return ids[sid.lower()], "id"
        url = event_url(payload).lower()
        if url:
            if url_path(url) in paths:
                return paths[url_path(url)], "url"
            hit = next((orig for low, orig in ids.items() if len(low) >= 4 and low in url), None)
            if hit:
                return hit, "url"
        candidates = names.get(norm(event_name(payload)), [])
        if len(candidates) == 1:
            return candidates[0][0], "name"
        if len(candidates) > 1 and event_price(payload) is not None:
            best = min(candidates, key=lambda c: abs((c[1] or 1e9) - event_price(payload)))
            return best[0], "name+price"
        return None, "unmatched"

    return match


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", type=Path, nargs="+", required=True, help="Run folder(s) or recsys_events.jsonl file(s).")
    ap.add_argument("--catalog", type=Path, required=True, help="CSV, Parquet or JSONL catalog.")
    ap.add_argument("--id-col", required=True, help="Catalog column holding the user's item ID.")
    ap.add_argument("--url-col", help="Catalog column with product page URLs or handles.")
    ap.add_argument("--name-col", help="Catalog column with product names (fallback match).")
    ap.add_argument("--price-col", help="Catalog column with prices (breaks name ties).")
    ap.add_argument("--interactions", type=Path, help="The user's interaction log, for coverage and merging.")
    ap.add_argument("--item-col", help="Item ID column in --interactions.")
    ap.add_argument("--user-col", help="User ID column in --interactions.")
    ap.add_argument("--event-col", help="Event type column in --interactions.")
    ap.add_argument("--cold-below", type=int, default=5, help="An item is cold with fewer interactions than this.")
    ap.add_argument("--out", type=Path, required=True, help="Output .parquet (augmented, or synthetic only without --interactions).")
    args = ap.parse_args(argv)

    catalog = read_table(args.catalog)
    events = load_events(args.events)
    events["item_id"] = events["item_id"].map(as_id)
    match = build_matcher(catalog, args.id_col, args.url_col, args.name_col, args.price_col)

    has_item = events["item_id"].notna()
    results = [match(s, p) if h else (None, "no_item") for s, p, h in zip(events["item_id"], events["payload"], has_item)]
    # An event without a name or URL (often item_selected) reuses the match of the same site ID in the same run.
    known = {(sess, sid): r[0] for sess, sid, r in zip(events["session_id"], events["item_id"], results) if r[0]}
    results = [
        (known[(sess, sid)], "same_id_in_run") if r[1] == "unmatched" and (sess, sid) in known else r
        for sess, sid, r in zip(events["session_id"], events["item_id"], results)
    ]
    events["catalog_item_id"] = [r[0] for r in results]
    events["match_method"] = [r[1] for r in results]
    item_events = events[has_item]
    matched = item_events[item_events["catalog_item_id"].notna()]
    dropped = item_events[item_events["catalog_item_id"].isna()]

    synth = pd.DataFrame({
        "user_id": matched["actor_id"], "item_id": matched["catalog_item_id"], "event_type": matched["event_type"],
        "signal_strength": matched["signal_strength"], "session_id": matched["session_id"],
        "site_item_id": matched["item_id"], "match_method": matched["match_method"], "is_synthetic": True,
    })

    report: dict[str, object] = {
        "item_events": int(len(item_events)), "matched": int(len(matched)), "dropped": int(len(dropped)),
        "match_methods": matched["match_method"].value_counts().to_dict(),
        "dropped_site_ids": sorted(map(str, dropped["item_id"].unique()))[:50],
        "synthetic_sessions": int(events["session_id"].nunique()),
    }

    out = synth
    if args.interactions:
        if not args.item_col:
            sys.exit("--item-col is required with --interactions.")
        real = read_table(args.interactions)
        counts = real[args.item_col].map(as_id).value_counts()
        all_items = catalog[args.id_col].map(as_id)
        cold = set(all_items[all_items.map(lambda i: counts.get(i, 0) < args.cold_below)])
        reached = set(synth["item_id"].astype(str)) & cold
        report.update(cold_items=len(cold), cold_items_with_new_signal=len(reached),
                      cold_items_still_without_signal=len(cold - reached))
        renamed = synth.rename(columns={"item_id": args.item_col, "user_id": args.user_col or "user_id",
                                        "event_type": args.event_col or "event_type"})
        real = real.assign(**{args.item_col: real[args.item_col].map(as_id)}, is_synthetic=False)
        out = pd.concat([real, renamed], ignore_index=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out, index=False)
    report["output"] = str(args.out)
    report["output_rows"] = int(len(out))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
