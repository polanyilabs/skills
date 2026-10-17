# Polanyi event schema (what the shoppers record)

Every row has `is_synthetic: true`, a synthetic `actor_id` (one per persona) and a `session_id`.

> Versions: this table describes the next `polanyi` release. In `polanyi` 0.4.2, `item_selected` and
> `checkout_started` are `very_strong`, and `session_started` does not record `max_price_usd` yet.

| event_type | Meaning | signal_strength |
|---|---|---|
| `session_started` | Visit began; `payload.max_price_usd` is the most this persona would pay, set before browsing | none |
| `search_submitted` | Searched the site (`payload.query`) | medium |
| `filter_applied` | Applied a filter or sort | medium |
| `item_impression` | Saw a product in a list and did not open it | weak |
| `item_viewed` | Opened a product page | weak |
| `item_clicked` | Clicked a product | medium |
| `item_selected` | Chose a product. `payload.selection_status: "research_only"` means shortlisted without adding to cart | strong (medium when research only) |
| `checkout_started` | Started checkout | strong |
| `checkout_boundary_stop` | Stopped at sign-in, identity or payment. Shoppers never sign in or pay | none |
| `inference_signal` | The shopper's own reading of its preferences (not an observed action) | ambiguous |
| `session_summary` | What was and was not captured | none |

Notes for modelling:
- An impression without a selection is an exposed non-choice, not a dislike.
- Actions the shopper reports as failed (a filter that errored, a page that did not load) are dropped when the events
  are written and listed in `session_summary.dropped_events`.
- Dwell time, scroll depth, ratings, reviews and purchases are never recorded; they are listed in `not_captured`.
