# How synthetic events are matched to the user's catalog

`scripts/merge_to_catalog.py` maps each event that names an item to one catalog ID, in this order:

1. **Site ID equals a catalog ID** (case-insensitive).
2. **Site ID contains a catalog ID as whole segments.** Stores often build handles from the name and the ID:
   `alexion-sweater-0874754` contains `0874754`. Segments are split on `-`, `_`, `/` and other punctuation, so `1001`
   never matches inside `10010`. IDs shorter than 4 characters only match exactly.
3. **Product URL.** The URL path or its last segment equals a catalog URL or handle (`--url-col`), or the path contains
   a catalog ID as whole segments.
4. **Product name equals exactly one catalog name** (`--name-col`). Names are compared in lower case with punctuation
   removed, in any script. When several products share a name, `--price-col` picks the closest price; without it, or
   when two prices are equally close, the event is dropped.
5. **Same site ID earlier in the same session.** Events like `item_selected` often carry only the ID; if that ID was
   matched on another event in the same session, the match is reused.

Anything ambiguous or unmatched is dropped and listed in `dropped_site_ids`. Nothing is guessed. All IDs are compared as
text, so zero-padded IDs (`0874754`) keep their zeros in every input format.

## Why matches fail

| Symptom | Cause | Fix |
|---|---|---|
| 0 matches by `id`, many by `name` | The site shows variant codes (one per colour or size) and the catalog lists products | Expected. Keep `--name-col`. |
| Most events dropped | Catalog does not include the categories the shoppers browsed | Narrow the brief to the catalog's categories, or export the full catalog |
| Dropped IDs look like collection or landing-page slugs | The shopper recorded a category page, not a product | Expected; these are not products |
| Products sharing a name are dropped | Several products have the same name and no `--price-col` was given | Pass `--price-col` |
| Names that differ slightly are dropped | Name matching is exact after normalising ("Strider Road 4 - Black" vs "Strider Road 4") | Pass `--url-col`; looser name matching is planned |

Example: a store shows one code per colour (`STR-04-BLK`, `STR-04-RED`) while the catalog lists the product
(`RUN-1001`, "Strider Road 4"). No event matches by ID, almost all match by name, and the `item_selected` event that
carries only `STR-04-BLK` reuses the name match from earlier in the session.
