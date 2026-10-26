#!/usr/bin/env python3
"""Map Polanyi synthetic events onto the user's own catalog IDs and report coverage.

Matching order for each event that names an item:
  1. the site's ID equals a catalog ID (case-insensitive)
  2. the site's ID contains a catalog ID as whole segments (e.g. "alexion-sweater-0874754" -> "0874754")
  3. the event's product URL equals a catalog URL or handle, or contains a catalog ID as whole segments
  4. the product name matches exactly one catalog name (with --price-col, the closest price breaks ties)
  5. the same site ID was matched on another event in the same session
Anything ambiguous or unmatched is dropped and counted, never guessed. IDs are always compared as strings,
so zero-padded IDs keep their zeros.

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

MIN_EMBEDDED_ID = 4  # shorter IDs only match exactly; "12" inside "size-12" is not a product
SEP = re.compile(r"([\W_]+)")


def read_table(path: Path, id_cols: list[str]) -> pd.DataFrame:
    """Read CSV, Parquet or JSONL. ID columns are read as text so "0874754" keeps its leading zero."""
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix in (".jsonl", ".json"):
        return pd.read_json(path, lines=path.suffix == ".jsonl", dtype=False, convert_dates=False)
    return pd.read_csv(path, dtype={c: str for c in id_cols})  # pandas ignores names that aren't columns


def load_events(paths: list[Path]) -> pd.DataFrame:
    files: list[Path] = []
    for p in paths:
        files += sorted(p.rglob("recsys_events.jsonl")) if p.is_dir() else [p]
    frames = [pd.read_json(f, lines=True, dtype=False, convert_dates=False) for f in files if f.stat().st_size > 0]
    frames = [f for f in frames if len(f)]
    if not frames:
        sys.exit("No events found under --events (no recsys_events.jsonl, or every session was empty or failed).")
    events = pd.concat(frames, ignore_index=True)
    if "event_id" in events:  # the Python SDK also writes every session's events into one merged file
        events = events.drop_duplicates(["session_id", "event_id"], ignore_index=True)
    for col in ("item_id", "payload", "session_id", "actor_id", "event_type", "signal_strength"):
        if col not in events:
            events[col] = None
    return events


def as_id(value: object) -> str | None:
    """One string form for IDs: pandas turns numeric IDs into floats when a column has gaps (1001 -> 1001.0)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text or None


def norm(text: object) -> str:
    """Lower-case and collapse punctuation; keeps letters from any script."""
    return SEP.sub(" ", str(text).lower()).strip()


def url_path(text: object) -> str:
    return urlparse(str(text)).path.strip("/").lower() if text else ""


def spans(text: str, max_parts: int = 6) -> list[str]:
    """Every run of whole segments in text: 'a-b_c' -> a, a-b, a-b_c, b, b_c, c."""
    parts = SEP.split(text)  # segments at even positions, separators at odd ones
    segs = range(0, len(parts), 2)
    return ["".join(parts[i:j + 1]) for i in segs for j in range(i, min(len(parts), i + 2 * max_parts), 2) if parts[i]]


def payload_get(payload: object, *keys: str) -> object:
    if not isinstance(payload, dict):
        return None
    return next((payload[k] for k in keys if payload.get(k) not in (None, "")), None)


def build_matcher(catalog: pd.DataFrame, id_col: str, url_col: str | None, name_col: str | None, price_col: str | None):
    cat_ids = [as_id(i) for i in catalog[id_col]]
    ids = {i.lower(): i for i in cat_ids if i}

    paths: dict[str, set[str]] = {}
    if url_col:
        for i, u in zip(cat_ids, catalog[url_col]):
            path = url_path(u) if i and pd.notna(u) else ""
            if path:
                paths.setdefault(path, set()).add(i)
                paths.setdefault(path.rsplit("/", 1)[-1], set()).add(i)  # handle only

    names: dict[str, list[tuple[str, float | None]]] = {}
    if name_col:
        prices = catalog[price_col] if price_col else [None] * len(catalog)
        for i, n, p in zip(cat_ids, catalog[name_col], prices):
            key = norm(n) if i and pd.notna(n) else ""
            if key:
                names.setdefault(key, []).append((i, float(p) if price_col and pd.notna(p) else None))

    def embedded(text: str) -> str | None:
        hits = {ids[s] for s in map(str.lower, spans(text)) if len(s) >= MIN_EMBEDDED_ID and s in ids}
        if not hits:
            return None
        longest = max(len(h) for h in hits)
        best = {h for h in hits if len(h) == longest}
        return best.pop() if len(best) == 1 else None  # two different IDs of equal length: ambiguous

    def match(site_id: object, payload: object) -> tuple[str | None, str]:
        sid = as_id(site_id)
        if sid and sid.lower() in ids:
            return ids[sid.lower()], "id"
        if sid and (hit := embedded(sid)):
            return hit, "id_in_site_id"
        url = payload_get(payload, "url", "product_url", "source_url")
        if url:
            path = url_path(url)
            for key in (path, path.rsplit("/", 1)[-1]):
                if key and len(paths.get(key, ())) == 1:
                    return next(iter(paths[key])), "url"
            if path and (hit := embedded(path)):
                return hit, "url"
        name = norm(payload_get(payload, "name", "title", "product_name") or "")
        candidates = names.get(name, []) if name else []
        if len(candidates) == 1:
            return candidates[0][0], "name"
        price = payload_get(payload, "price_usd", "selected_price_usd")
        if len(candidates) > 1 and price_col and isinstance(price, (int, float)):
            priced = sorted((abs(c[1] - price), c[0]) for c in candidates if c[1] is not None)
            if priced and (len(priced) == 1 or priced[0][0] < priced[1][0]):
                return priced[0][1], "name+price"
        return None, "unmatched"

    return match


def fit_to_log(synth: pd.DataFrame, real: pd.DataFrame, args: argparse.Namespace, report: dict) -> pd.DataFrame:
    """Write synthetic rows in the log's own schema: its column names, ID types, event names and time column."""
    if args.event_map:
        mapping = dict(pair.split("=", 1) for pair in args.event_map.split(","))
        keep = synth["event_type"].isin(mapping)
        report["events_not_in_event_map"] = int((~keep).sum())
        synth = synth[keep].assign(event_type=synth.loc[keep, "event_type"].map(mapping))
    synth = synth.assign(synthetic_actor_id=synth["user_id"])
    if pd.api.types.is_numeric_dtype(real[args.user_col]):
        # Integer user IDs stay integers: synthetic users become -1, -2, ..., which never collide with real ones.
        codes = {a: -(i + 1) for i, a in enumerate(sorted(synth["user_id"].unique()))}
        synth = synth.assign(user_id=synth["user_id"].map(codes))
    if pd.api.types.is_numeric_dtype(real[args.item_col]):
        ids = pd.to_numeric(synth["item_id"], errors="coerce")
        if ids.isna().any():
            sys.exit(f"--item-col {args.item_col!r} is numeric but these catalog IDs are not: "
                     f"{sorted(synth.loc[ids.isna(), 'item_id'].unique())[:5]}")
        synth = synth.assign(item_id=ids.astype(real[args.item_col].dtype))
    renames = {"item_id": args.item_col, "user_id": args.user_col, "event_type": args.event_col}
    if args.time_col:
        dates = synth["session_date"]
        synth = synth.assign(session_date=pd.to_datetime(dates) if pd.api.types.is_datetime64_any_dtype(real[args.time_col]) else dates)
        renames["session_date"] = args.time_col
    return synth.rename(columns=renames)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", type=Path, nargs="+", required=True, help="Run folder(s) or recsys_events.jsonl file(s).")
    ap.add_argument("--catalog", type=Path, required=True, help="CSV, Parquet or JSONL catalog.")
    ap.add_argument("--id-col", required=True, help="Catalog column holding the user's item ID.")
    ap.add_argument("--url-col", help="Catalog column with product page URLs or handles.")
    ap.add_argument("--name-col", help="Catalog column with product names (fallback match).")
    ap.add_argument("--price-col", help="Catalog column with prices (breaks ties between products with the same name).")
    ap.add_argument("--interactions", type=Path, help="The user's interaction log (CSV, Parquet or JSONL).")
    ap.add_argument("--item-col", help="Item ID column in --interactions (required with it).")
    ap.add_argument("--user-col", help="User ID column in --interactions (required with it).")
    ap.add_argument("--event-col", help="Event type column in --interactions (required with it; created if absent).")
    ap.add_argument("--event-map", help="Polanyi event -> your event name, e.g. item_viewed=view,item_selected=add_to_cart. "
                                        "Synthetic events not listed are dropped.")
    ap.add_argument("--time-col", help="Time column in --interactions; synthetic rows get their session date.")
    ap.add_argument("--cold-below", type=int, default=5, help="An item is cold with fewer interactions than this.")
    ap.add_argument("--out", type=Path, required=True, help="Output .parquet or .csv.")
    args = ap.parse_args(argv)

    if args.interactions and not (args.item_col and args.user_col and args.event_col):
        sys.exit("--item-col, --user-col and --event-col are all required with --interactions.")
    if args.out.suffix not in (".parquet", ".csv"):
        sys.exit(f"--out must end in .parquet or .csv, got {args.out.name}")

    catalog = read_table(args.catalog, [args.id_col])
    if args.id_col not in catalog:
        sys.exit(f"--id-col {args.id_col!r} is not a catalog column: {list(catalog.columns)}")
    events = load_events(args.events)
    events["item_id"] = events["item_id"].map(as_id)
    match = build_matcher(catalog, args.id_col, args.url_col, args.name_col, args.price_col)

    has_item = events["item_id"].notna()
    results = [match(s, p) if h else (None, "no_item") for s, p, h in zip(events["item_id"], events["payload"], has_item)]
    # An event without a name or URL (often item_selected) reuses the match of the same site ID in the same session.
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
        "user_id": matched["actor_id"].map(as_id), "item_id": matched["catalog_item_id"],
        "event_type": matched["event_type"], "signal_strength": matched["signal_strength"],
        "session_id": matched["session_id"], "site_item_id": matched["item_id"],
        "match_method": matched["match_method"], "is_synthetic": True,
        "session_date": matched["recorded_date"] if "recorded_date" in matched else None,
    })

    report: dict[str, object] = {
        "item_events": int(len(item_events)), "matched": int(len(matched)), "dropped": int(len(dropped)),
        "match_methods": matched["match_method"].value_counts().to_dict(),
        "matched_by_signal": matched["signal_strength"].value_counts().to_dict(),
        "dropped_site_ids": sorted(dropped["item_id"].unique())[:50],
        "events_without_item": int((~has_item).sum()),
        "synthetic_sessions": int(events["session_id"].nunique()),
    }

    out = synth
    if args.interactions:
        real = read_table(args.interactions, [args.item_col, args.user_col])
        for col in (args.item_col, args.user_col, *([args.time_col] if args.time_col else [])):
            if col not in real:
                sys.exit(f"{col!r} is not a column of --interactions: {list(real.columns)}")
        counts = real[args.item_col].map(as_id).value_counts()  # compare as text; the log itself is not changed
        all_items = pd.Series(catalog[args.id_col].map(as_id).dropna().unique())
        cold = set(all_items[all_items.map(lambda i: counts.get(i, 0) < args.cold_below)])
        reached = set(synth["item_id"]) & cold
        selected = set(synth.loc[synth["event_type"] == "item_selected", "item_id"]) & cold
        report.update(cold_items=len(cold), cold_items_with_new_signal=len(reached),
                      cold_items_with_a_selection=len(selected), cold_items_still_without_signal=len(cold - reached))
        out = pd.concat([real.assign(is_synthetic=False), fit_to_log(synth, real, args, report)], ignore_index=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    (out.to_csv if args.out.suffix == ".csv" else out.to_parquet)(args.out, index=False)
    report["output"] = str(args.out)
    report["output_rows"] = int(len(out))
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
