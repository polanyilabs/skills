import json
import sys
from pathlib import Path

import pandas as pd
import pytest

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
          "--user-col", "user_id", "--event-col", "event", "--out", str(tmp_path / "o.parquet")])
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


def _run(tmp_path, capsys, events, catalog, *extra, real=None, out="o.parquet"):
    (tmp_path / "recsys_events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    catalog.to_csv(tmp_path / "c.csv", index=False)
    args = ["--events", str(tmp_path / "recsys_events.jsonl"), "--catalog", str(tmp_path / "c.csv"),
            "--id-col", "product_id", *extra, "--out", str(tmp_path / out)]
    if real is not None:
        real.to_csv(tmp_path / "real.csv", index=False)
        args += ["--interactions", str(tmp_path / "real.csv"), "--item-col", "item_id",
                 "--user-col", "user_id", "--event-col", "event"]
    main(args)
    return json.loads(capsys.readouterr().out)


def test_zero_padded_ids_keep_their_zeros(tmp_path, capsys):
    report = _run(tmp_path, capsys, [_event("0874754", {})],
                  pd.DataFrame({"product_id": ["0874754", "0889652"]}),
                  real=pd.DataFrame({"user_id": ["u1"] * 5, "item_id": ["0889652"] * 5, "event": ["buy"] * 5}))
    assert report["matched"] == 1 and report["cold_items"] == 1
    merged = pd.read_parquet(tmp_path / "o.parquet")
    assert set(merged["item_id"]) == {"0874754", "0889652"}


def test_numeric_user_ids_do_not_crash_the_write(tmp_path, capsys):
    report = _run(tmp_path, capsys, [_event("A-1", {})], pd.DataFrame({"product_id": ["A-1"]}),
                  real=pd.DataFrame({"user_id": [101, 102], "item_id": ["A-1", "A-1"], "event": ["view", "view"]}))
    assert report["output_rows"] == 3


def test_catalog_id_inside_a_slug_handle_matches_whole_segments_only(tmp_path, capsys):
    events = [_event("alexion-sweater-0874754", {}, "item_selected"),
              _event("x", {"url": "https://store.example/products/10010"})]
    report = _run(tmp_path, capsys, events, pd.DataFrame({"product_id": ["0874754", "1001", "10010"]}))
    merged = pd.read_parquet(tmp_path / "o.parquet")
    assert report["dropped"] == 0
    assert list(merged["item_id"]) == ["0874754", "10010"]


def test_ambiguous_or_empty_keys_are_dropped_not_guessed(tmp_path, capsys):
    events = [_event("a", {"name": "Easy Miles 14", "price_usd": 95}),       # duplicate name, no --price-col
              _event("b", {"name": "トレイルシューズ", "price_usd": 100}),     # non-Latin name that is not in the catalog
              _event("c", {"url": "https://store.example/"})]                # home page vs a blank catalog URL
    catalog = pd.DataFrame({"product_id": ["P-1", "P-2", "J-1", "H-1"],
                            "title": ["Easy Miles 14", "Easy Miles 14", "ランニングシューズ", "Home"],
                            "url": ["", "", "", ""]})
    report = _run(tmp_path, capsys, events, catalog, "--name-col", "title", "--url-col", "url")
    assert report["matched"] == 0 and report["dropped"] == 3


def test_free_items_break_ties_by_price(tmp_path, capsys):
    catalog = pd.DataFrame({"product_id": ["F-0", "F-50"], "title": ["Gift", "Gift"], "price": [0, 50]})
    report = _run(tmp_path, capsys, [_event("g", {"name": "Gift", "price_usd": 0})], catalog,
                  "--name-col", "title", "--price-col", "price")
    assert report["match_methods"] == {"name+price": 1}
    assert list(pd.read_parquet(tmp_path / "o.parquet")["item_id"]) == ["F-0"]


def test_csv_output_is_csv(tmp_path, capsys):
    _run(tmp_path, capsys, [_event("A-1", {})], pd.DataFrame({"product_id": ["A-1"]}), out="o.csv")
    assert (tmp_path / "o.csv").read_text().startswith("user_id,")


def test_missing_columns_and_empty_runs_fail_with_a_message(tmp_path):
    (tmp_path / "recsys_events.jsonl").write_text("")
    pd.DataFrame({"product_id": ["A-1"]}).to_csv(tmp_path / "c.csv", index=False)
    base = ["--events", str(tmp_path / "recsys_events.jsonl"), "--catalog", str(tmp_path / "c.csv"),
            "--id-col", "product_id", "--out", str(tmp_path / "o.parquet")]
    with pytest.raises(SystemExit, match="No events found"):
        main(base)
    with pytest.raises(SystemExit, match="are all required"):
        main(base + ["--interactions", str(tmp_path / "c.csv"), "--item-col", "product_id"])


def test_synthetic_rows_follow_the_logs_schema(tmp_path, capsys):
    # A log with integer IDs, its own event names and a datetime column.
    events = [dict(_event(1002, {}), recorded_date="2026-10-17"),
              dict(_event(1002, {}, "item_selected"), recorded_date="2026-10-17"),
              dict(_event(1002, {}, "inference_signal"), recorded_date="2026-10-17")]
    (tmp_path / "recsys_events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    pd.DataFrame({"product_id": [1001, 1002]}).to_csv(tmp_path / "c.csv", index=False)
    pd.DataFrame({"customer": [7, 8], "sku": [1001, 1001], "action": ["view", "buy"],
                  "ts": pd.to_datetime(["2026-09-01", "2026-09-02"])}).to_parquet(tmp_path / "real.parquet")

    main(["--events", str(tmp_path / "recsys_events.jsonl"), "--catalog", str(tmp_path / "c.csv"), "--id-col", "product_id",
          "--interactions", str(tmp_path / "real.parquet"), "--item-col", "sku", "--user-col", "customer",
          "--event-col", "action", "--event-map", "item_impression=view,item_selected=cart", "--time-col", "ts",
          "--out", str(tmp_path / "o.parquet")])
    report = json.loads(capsys.readouterr().out)
    out = pd.read_parquet(tmp_path / "o.parquet")
    synth = out[out["is_synthetic"]]

    assert report["events_not_in_event_map"] == 1
    assert out["customer"].dtype.kind == "i" and out["sku"].dtype.kind == "i" and out["ts"].dtype.kind == "M"
    assert list(synth["customer"]) == [-1, -1] and list(synth["sku"]) == [1002, 1002]
    assert list(synth["action"]) == ["view", "cart"] and synth["synthetic_actor_id"].iloc[0] == "syn_a"
    assert str(synth["ts"].iloc[0].date()) == "2026-10-17"


def test_sdk_output_folder_is_not_counted_twice(tmp_path, capsys):
    # Client.simulate() writes each session's events and a merged copy at the top of the run folder.
    events = [dict(_event("A-1", {}), event_id="evt_0001"), dict(_event("A-1", {}, "item_selected"), event_id="evt_0002")]
    lines = "\n".join(json.dumps(e) for e in events)
    (tmp_path / "run" / "0000_mary").mkdir(parents=True)
    (tmp_path / "run" / "0000_mary" / "recsys_events.jsonl").write_text(lines)
    (tmp_path / "run" / "recsys_events.jsonl").write_text(lines)
    pd.DataFrame({"product_id": ["A-1"]}).to_csv(tmp_path / "c.csv", index=False)

    main(["--events", str(tmp_path / "run"), "--catalog", str(tmp_path / "c.csv"), "--id-col", "product_id",
          "--out", str(tmp_path / "o.parquet")])
    assert json.loads(capsys.readouterr().out)["matched"] == 2


def test_coverage_json_lists_cold_items_reached_and_still_dark(tmp_path, capsys):
    run = tmp_path / "run"
    run.mkdir()
    events = [_event("TRL-1", {}), dict(_event("TRL-2", {}), signal_strength="medium"),
              _event("TRL-2", {}, "item_selected"), _event("RUN-1", {})]
    (run / "recsys_events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    pd.DataFrame({"product_id": ["RUN-1", "TRL-1", "TRL-2", "TRL-3", "DRS-1"],
                  "title": ["Road", "Ridge", "Switchback", "Summit", None],
                  "kind": ["Road", "Trail", "Trail", "Trail", "Dress"]}).to_csv(tmp_path / "c.csv", index=False)
    pd.DataFrame({"user_id": ["u1"] * 5, "item_id": ["RUN-1"] * 5, "event": ["view"] * 5}).to_csv(tmp_path / "r.csv", index=False)

    main(["--events", str(run), "--catalog", str(tmp_path / "c.csv"), "--id-col", "product_id", "--name-col", "title",
          "--type-col", "kind", "--interactions", str(tmp_path / "r.csv"), "--item-col", "item_id",
          "--user-col", "user_id", "--event-col", "event", "--out", str(tmp_path / "o.parquet")])
    report = json.loads(capsys.readouterr().out)
    coverage = json.loads((run / "coverage.json").read_text())

    assert report["coverage"] == str(run / "coverage.json")
    assert coverage["cold_items"] == 4 and coverage["chosen"] == 1
    assert [(r["name"], r["type"], r["signal"]) for r in coverage["reached"]] == [
        ("Switchback", "Trail", "chosen"), ("Ridge", "Trail", "seen")]
    assert coverage["still_without_signal"] == {"Dress": 1, "Trail": 1}


def test_no_coverage_file_without_a_run_folder(tmp_path, capsys):
    report = _run(tmp_path, capsys, [_event("A-1", {})], pd.DataFrame({"product_id": ["A-1", "B-2"]}),
                  real=pd.DataFrame({"user_id": ["u1"], "item_id": ["A-1"], "event": ["view"]}))
    assert "coverage" not in report and not (tmp_path / "coverage.json").exists()
