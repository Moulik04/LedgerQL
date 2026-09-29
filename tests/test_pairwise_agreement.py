import json

from evals.pairwise_agreement import load_model, main, pair_stats


def _rec(id_, correct, rows, reason=None):
    return {
        "id": id_,
        "reason_code": reason,
        "execution_correct": correct,
        "rows": rows,
        "candidates": [],
    }


def test_load_model_maps_gen_only_records_to_the_signal_row_shape(tmp_path):
    path = tmp_path / "m.jsonl"
    path.write_text(
        "".join(
            json.dumps(r) + "\n"
            for r in (_rec("A", True, [[1]]), _rec("B", False, [], reason="EXEC_ERROR"))
        )
    )
    rows = load_model(path)
    assert rows[0] == {"id": "A", "answered": True, "winner_correct": True, "winner_rows": [[1]]}
    # A case where every candidate failed has no winner: it did not "answer".
    assert rows[1]["answered"] is False


def test_pair_stats_reports_auroc_and_the_agreement_policy_in_both_directions():
    a = [
        {"id": f"c{i}", "answered": True, "winner_correct": ok, "winner_rows": [(v,)]}
        for i, (ok, v) in enumerate([(True, 1), (True, 2), (True, 3), (False, 4), (False, 5)])
    ]
    # B agrees on every correct case and disagrees on both wrong ones.
    b = [
        {"id": f"c{i}", "answered": True, "winner_correct": ok, "winner_rows": [(v,)]}
        for i, (ok, v) in enumerate([(True, 1), (True, 2), (True, 3), (True, 40), (True, 50)])
    ]
    stats = pair_stats(a, b)
    assert stats["n_both_answered"] == 5
    assert stats["auroc"] == 1.0  # match perfectly ranks A's correct above A's wrong
    assert stats["policy"] == {"answered": 3, "correct": 3, "wrong": 0}
    assert stats["buckets"]["differ"] == {"n": 2, "correct": 0, "wrong": 2}


def test_pair_stats_auroc_is_none_when_one_class_is_empty():
    a = [{"id": "c", "answered": True, "winner_correct": True, "winner_rows": [(1,)]}]
    assert pair_stats(a, a)["auroc"] is None


def test_main_prints_every_ordered_pair(tmp_path, capsys):
    paths = []
    for name, val in (("m1", 1), ("m2", 1), ("m3", 2)):
        path = tmp_path / f"{name}.jsonl"
        path.write_text(json.dumps(_rec("A", val == 1, [[val]])) + "\n")
        paths.append(f"{name}={path}")
    assert main(paths) == 0
    out = capsys.readouterr().out
    for pair in ("m1 -> m2", "m2 -> m1", "m1 -> m3", "m3 -> m1", "m2 -> m3", "m3 -> m2"):
        assert pair in out
