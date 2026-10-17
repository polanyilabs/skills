---
name: polanyi-augment
description: "Augment a recommender dataset with synthetic shopper sessions on the user's own store, aimed at products with little or no behavioural history. Reads their catalog and interaction logs, finds cold items, runs persona shoppers with Polanyi, and merges the events onto their own item IDs. Use when the user mentions 'augment my data', 'cold start', 'new products have no data', 'sparse interactions', 'synthetic users/shoppers', or 'warm up a recommender'."
license: Apache-2.0
compatibility: Requires the polanyi Python package (pip install polanyi), Python 3.11+, pandas and pyarrow, and a Polanyi or Browser Use API key in the environment.
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
- Show the plan and wait for an explicit "yes" before any run. Runs cost money and take several minutes per shopper.
- Keep every synthetic row marked `is_synthetic=True` so it can be filtered out or down-weighted later.
- Report what was dropped during matching, with counts.

Don't:
- Run on a site the user does not own or operate, unless they confirm they have permission.
- Ask the user to paste API keys into the chat. They set `POLANYI_API_KEY` (or `BROWSER_USE_API_KEY`) in their environment or `.env`.
- Script how visits end ("then abandon", "pick one"). The brief says what to look for; each persona decides.
- Claim the recommender improved. This skill adds coverage; measuring lift is a separate experiment.

## Workflow

### 1. Understand the data (no run yet)

Load the catalog and interactions with pandas. Count interactions per catalog item; an item is **cold** when it has
fewer than 5 (say which threshold you used). If the catalog has a category column, group cold items by category.
If the user only asked which items are cold, stop here and answer.

### 2. Present the plan and wait for approval

```
Store:         https://store.example
Cold items:    23 of 410 (mostly: trail, outerwear)
Shoppers:      40 personas, 1 session each
Brief:         "Look for trail running shoes or waterproof outerwear for your own use or as a gift."
Estimate:      approximate: 5-10 min and a few cents to a few tens of cents per shopper,
               depending on the site and the model; check current pricing on your Polanyi account
Output:        <path the user gave>/augmented.parquet
Defaults:      synthetic rows flagged; unmatched events dropped and reported
Approve?
```

### 3. Run the shoppers

```bash
polanyi-sim --site https://store.example \
  --prompt "Look for trail running shoes or waterproof outerwear for your own use or as a gift." \
  --batch 40 --concurrency 5 --output-dir runs/augment-2026-10-16
```

Each shopper writes `runs/.../<index>_<persona>/recsys_events.jsonl`. Watch for failed sessions in the summary and
report them; do not rerun silently.

### 4. Merge onto the user's IDs

```bash
python scripts/merge_to_catalog.py --events runs/augment-2026-10-16 \
  --catalog catalog.csv --id-col product_id --name-col title --price-col price --url-col url \
  --interactions interactions.parquet --item-col item_id --user-col user_id --event-col event \
  --out augmented.parquet
```

The catalog and interactions can be CSV, Parquet or JSONL; pass them as they are. Pass `--name-col` and `--url-col`
whenever the catalog has them: sites often show variant codes (one per colour)
while catalogs list the product, so names and URLs carry most matches. See `references/id-matching.md`.

### 5. Report

Print a short table from the script's JSON output:

| | |
|---|---|
| Synthetic sessions | 40 |
| Item events matched / dropped | 612 / 41 |
| Cold items with new signal | 17 of 23 |
| Output | augmented.parquet (real rows + synthetic rows) |

Then one line on what is still missing (cold items no shopper reached) and a reminder that lift should be measured
by training with and without the synthetic rows and testing on held-out real data.

## References

| When | Read |
|---|---|
| Explaining the event types and signal strengths | `references/event-schema.md` |
| Many events were dropped, or IDs look wrong | `references/id-matching.md` |
