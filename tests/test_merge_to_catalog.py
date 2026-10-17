import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "skills/polanyi-augment/scripts"))
from merge_to_catalog import main  # noqa: E402


def _event(item_id, payload, event_type="item_impression"):
    return {"session_id": "s1", "actor_id": "syn_a", "event_type": event_type, "signal_strength": "weak",
            "item_id": item_id, "payload": payload}


def test_matches_by_id_url_and_name_and_drops_the_rest(tmp_path, capsys):
    run = tmp_path / "run"
    run.mkdir()
    events = [
        _event(None, {"url": "https://store.example/"}, "session_started"),
        _event("RUN-1001", {}),                                                     # 1. exact ID
        _event("tempo-glide", {"url": "https://store.example/t/tempo/RUN-1002"}),   # 2. ID inside URL
        _event("daily-pacer", {"url": "https://store.example/products/daily-pacer"}),  # 2. catalog URL path
        _event("x1", {"name": "Easy Miles 14", "price_usd": 75}),                  # 3. name + price
        _event("summer-collection", {"url": "https://store.example/collections/summer"}),  # collection page: dropped
    ]
    (run / "recsys_events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    catalog = pd.DataFrame({
        "product_id": ["RUN-1001", "RUN-1002", "RUN-1003", "RUN-1004", "RUN-1005", "NEW-1"],
        "title": ["Strider Road 4", "Tempo Glide 2", "Daily Pacer", "Easy Miles 14", "Easy Miles 14", "New drop"],
        "price": [165, 145, 104, 75, 95, 120],
        "url": ["", "", "https://store.example/products/daily-pacer", "", "", ""],
    })
    catalog.to_csv(tmp_path / "catalog.csv", index=False)
    real = pd.DataFrame({"user_id": ["u1"] * 6, "item_id": ["RUN-1001"] * 6, "event": ["view"] * 6})
    real.to_parquet(tmp_path / "real.parquet")

    out = tmp_path / "augmented.parquet"
    assert main(["--events", str(run), "--catalog", str(tmp_path / "catalog.csv"), "--id-col", "product_id",
                 "--url-col", "url", "--name-col", "title", "--price-col", "price",
                 "--interactions", str(tmp_path / "real.parquet"), "--item-col", "item_id",
                 "--user-col", "user_id", "--event-col", "event", "--out", str(out)]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["matched"] == 4 and report["dropped"] == 1
    assert report["dropped_site_ids"] == ["summer-collection"]
    assert report["match_methods"] == {"id": 1, "url": 2, "name+price": 1}
    assert report["cold_items"] == 5 and report["cold_items_with_new_signal"] == 3

    merged = pd.read_parquet(out)
    synth = merged[merged["is_synthetic"]]
    assert set(synth["item_id"]) == {"RUN-1001", "RUN-1002", "RUN-1003", "RUN-1004"}
    assert len(merged) == 6 + 4


def test_numeric_ids_survive_missing_values(tmp_path, capsys):
    # Shopify-style numeric IDs; session_started has no item, which used to turn 1001 into 1001.0.
    events = [_event(None, {}, "session_started"), _event(1001, {}), _event(1002, {}, "item_selected")]
    (tmp_path / "recsys_events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    pd.DataFrame({"product_id": [1001, 1002, 1003]}).to_csv(tmp_path / "c.csv", index=False)
    pd.DataFrame({"user_id": ["u1", "u2"], "item_id": [1001.0, None]}).to_csv(tmp_path / "real.csv", index=False)

    main(["--events", str(tmp_path / "recsys_events.jsonl"), "--catalog", str(tmp_path / "c.csv"),
          "--id-col", "product_id", "--interactions", str(tmp_path / "real.csv"), "--item-col", "item_id",
          "--out", str(tmp_path / "o.parquet")])
    report = json.loads(capsys.readouterr().out)

    assert report["matched"] == 2 and report["dropped"] == 0
    assert report["cold_items"] == 3 and report["cold_items_with_new_signal"] == 2


def test_selection_without_name_reuses_the_match_from_the_same_run(tmp_path, capsys):
    # Impressions carry the name; the item_selected event only the per-colour code.
    events = [
        _event("STR-04-BLK", {"name": "Strider Road 4", "price_usd": 165}),
        _event("STR-04-BLK", {"selection_status": "selected"}, "item_selected"),
    ]
    (tmp_path / "recsys_events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    pd.DataFrame({"product_id": ["RUN-1001"], "title": ["Strider Road 4"]}).to_csv(tmp_path / "c.csv", index=False)

    main(["--events", str(tmp_path / "recsys_events.jsonl"), "--catalog", str(tmp_path / "c.csv"),
          "--id-col", "product_id", "--name-col", "title", "--out", str(tmp_path / "o.parquet")])
    report = json.loads(capsys.readouterr().out)

    assert report["matched"] == 2 and report["dropped"] == 0
    assert report["match_methods"] == {"name": 1, "same_id_in_run": 1}
