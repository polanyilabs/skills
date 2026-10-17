# How synthetic events are matched to the user's catalog

`scripts/merge_to_catalog.py` maps each event that names an item to one catalog ID, in this order:

1. **Site ID equals a catalog ID** (case-insensitive). Works when the catalog uses the same IDs the site shows.
2. **The product URL contains a catalog ID, or equals a catalog URL path.** Needs `--url-col`, or IDs that appear in
   the site's URLs.
3. **Product name equals a catalog name.** Needs `--name-col`. With several products of the same name, `--price-col`
   picks the closest price.
4. **Same site ID earlier in the same session.** Events like `item_selected` often carry only the ID; if that ID was
   matched on another event in the same session, the match is reused.

Anything else is dropped and listed in `dropped_site_ids`. Nothing is guessed.

## Why matches fail

| Symptom | Cause | Fix |
|---|---|---|
| 0 matches by `id`, many by `name` | The site shows variant codes (one per colour or size) and the catalog lists products | Expected. Keep `--name-col`. |
| Most events dropped | Catalog does not include the categories the shoppers browsed | Narrow the brief to the catalog's categories, or export the full catalog |
| Dropped IDs look like collection or landing-page slugs | The shopper recorded a category page, not a product | Expected; these are not products |
| Name matches go to the wrong product | Several products share a name and no price column was given | Pass `--price-col` |

Example: a store shows one code per colour (`STR-04-BLK`, `STR-04-RED`) while the catalog lists the product
(`RUN-1001`, "Strider Road 4"). No event matches by ID, almost all match by name, and the `item_selected` event that
carries only `STR-04-BLK` reuses the name match from earlier in the session.
