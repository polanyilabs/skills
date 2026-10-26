---
name: polanyi-augment
description: "Augment a recommender dataset with synthetic shopper sessions on a live store, aimed at products with little or no behavioural history. Reads their catalog and interaction logs, finds cold items, runs persona shoppers with Polanyi, and merges the events onto their own item IDs. Use when the user mentions 'augment my data', 'cold start', 'new products have no data', 'sparse interactions', 'synthetic users/shoppers', or 'warm up a recommender'."
license: Apache-2.0
compatibility: Requires the polanyi Python package >= 0.4.2 (pip install polanyi), Python 3.11+, pandas and pyarrow, a Polanyi or Browser Use API key in the environment, and a store reachable from the public internet.
metadata:
  version: "0.1.0"
---

# Polanyi: augment a recommender dataset

Polanyi sends AI shoppers, each built from a synthetic persona, to browse the user's live store and records what they
search, view, compare, shortlist and choose as recommender events. This skill points those shoppers at the products
the user's data is missing, then merges the result into the user's own interaction log.

## Rules

Do:
- Ask for the store URL, the catalog file and its item-ID column, the interaction log and its columns, and the output path. Never guess them.
- Check that the store URL is reachable from the public internet. Shoppers run in the cloud, so `localhost`, VPN-only
  or password-protected staging sites fail. Ask about this before planning.
- Before showing the plan, check that `POLANYI_API_KEY` or `BROWSER_USE_API_KEY` is set. Check the name only; never
  print the value. If neither is set, tell the user how to set it and stop.
- Any public site the user names works, like the `polanyi-sim` CLI. Which site to browse is the user's decision, not
  yours: do not refuse a site because it isn't theirs. If it isn't their own store, add the `Note:` line to the plan
  and let them approve or change it.
- Show the plan and wait for an explicit "yes" before any run. Runs cost money and take several minutes per shopper.
- Keep every synthetic row marked `is_synthetic=True` so it can be filtered out or down-weighted later.
- Report what was dropped during matching, with counts.

Don't:
- Ask the user to paste API keys into the chat. They set `POLANYI_API_KEY` (or `BROWSER_USE_API_KEY`) in their environment or `.env`.
- Script how visits end ("then abandon", "pick one"). The brief says what to look for; each persona decides.
- Claim the recommender improved. This skill adds coverage; measuring lift is a separate experiment.

## Workflow

### 1. Understand the data (no run yet)

Load the catalog and interactions with pandas. Count interactions per catalog item; an item is **cold** when it has
fewer than 5 (say which threshold you used). If the catalog has a category column, group cold items by category.
If the user only asked which items are cold, stop here and answer.

Also read the log's schema, so synthetic rows can be written in the same shape:
- the user, item, event and time columns, and the type of each ID column (integer or text);
- the event names the log uses (e.g. `view`, `add_to_cart`, `purchase`).

Propose an event map from Polanyi's events to the log's names (for example `item_viewed=view,item_selected=add_to_cart`).
Never map anything to a purchase or order event: shoppers never buy. If the log only has purchases, keep Polanyi's
own event names and say so.

### 2. Present the plan and wait for approval

Choose the number of shoppers from the data: 5 × the number of cold categories, at least 5 and at most 40 for a
first run (one cold category: 5 shoppers; three: 15). Say how you chose it. Build the brief only from categories that are actually cold in this catalog.

```
Store:         <store URL, confirmed reachable from the internet>
Cold items:    <n> of <total> (mostly: <cold categories>)
Shoppers:      <N> personas, 1 session each (<why this number>)
Brief:         "Look for <cold categories> for your own use or as a gift."
Estimate:      approximate: 5-10 min and a few cents to a few tens of cents per shopper, depending on the site
               and the model. Total: about <N / concurrency x 10> min and <N x per-shopper cost>. Check current
               pricing on your Polanyi account.
Output:        <path the user gave>/augmented.parquet (or .csv)
Schema:        user_id <int|text>, item_id <int|text>, events mapped as <event map, or "kept as Polanyi names">,
               time column <name, or none>
Defaults:      synthetic rows flagged; unmatched events dropped and reported
Note:          (only if the site isn't the user's) its terms may not allow automated browsing, and its product IDs
               only match a catalog exported from that site
Approve?
```

### 3. Run the shoppers

```bash
polanyi-sim --site <store URL> \
  --prompt "<the approved brief>" \
  --batch <N> --concurrency 5 --output-dir runs/augment-<date>
```

Each shopper writes `runs/.../<index>_<persona>/recsys_events.jsonl`. Watch for failed sessions in the summary and
report them; do not rerun silently.

### 4. Merge onto the user's IDs

```bash
python scripts/merge_to_catalog.py --events runs/augment-<date> \
  --catalog catalog.csv --id-col product_id --name-col title --price-col price --url-col url \
  --interactions interactions.parquet --item-col item_id --user-col user_id --event-col event \
  --event-map item_viewed=view,item_selected=add_to_cart --time-col date \
  --out augmented.parquet
```

- The catalog and interactions can be CSV, Parquet or JSONL; pass them as they are. IDs are read as text, so
  zero-padded IDs keep their zeros. `--out` ends in `.parquet` or `.csv`.
- With `--interactions`, `--item-col`, `--user-col` and `--event-col` are all required, using the log's own column
  names. If the log has no event column, name one and it is created.
- Synthetic rows follow the log's schema: integer user IDs become -1, -2, ... (the `syn_...` name is kept in
  `synthetic_actor_id`), integer item IDs stay integers, `--event-map` renames events and drops the ones it doesn't
  list, and `--time-col` gets each session's date. The real rows are never changed.
- Pass `--name-col` and `--url-col` whenever the catalog has them. Matching tries the catalog ID first (also inside
  the store's own IDs, such as `alexion-sweater-0874754`), then URLs, then names. See `references/id-matching.md`.

### 5. Report

Print a short table from the script's JSON output:

| | |
|---|---|
| Synthetic sessions | 40 |
| Item events matched / dropped | 612 / 41 |
| Cold items with new signal / with a selection | 17 of 23 / 6 |
| Output | augmented.parquet (real rows + synthetic rows) |

Then one line on what is still missing (cold items no shopper reached) and a reminder that lift should be measured
by training with and without the synthetic rows and testing on held-out real data.

## References

| When | Read |
|---|---|
| Explaining the event types and signal strengths | `references/event-schema.md` |
| Many events were dropped, or IDs look wrong | `references/id-matching.md` |
