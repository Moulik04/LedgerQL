"""The pin on the measurement code and environment (evals/measurement_pin.py): what is in it,
that nothing a held-out figure depends on is left out, and that a held-out run is refused unless
the working tree and the environment match it."""

import json
from pathlib import Path

import pytest

from evals import measurement_pin as M
from evals import run_env
from evals.scoring import FrozenGoldError

# --- the list ---------------------------------------------------------------------------------


def test_every_pinned_file_exists_and_none_is_both_pinned_and_excluded():
    assert [rel for rel, digest in M.file_hashes().items() if digest is None] == []
    assert set(M.PINNED) & set(M.NOT_PINNED) == set()
    assert set(M.ENTRY_POINTS) <= set(M.PINNED)


def test_everything_a_heldout_entry_point_imports_is_pinned():
    closure = M.import_closure(M.ENTRY_POINTS, M.evals_imports())
    assert sorted(closure - set(M.PINNED)) == []


def test_every_evals_module_is_pinned_or_excluded_with_a_reason():
    modules = {f"evals/{p.name}" for p in (M.REPO / "evals").glob("*.py")}
    assert sorted(modules - set(M.PINNED) - set(M.NOT_PINNED)) == []
    assert sorted(set(M.NOT_PINNED) - modules) == []  # no reason left behind for a deleted file
    assert all(len(reason) > 20 for reason in M.NOT_PINNED.values())


def test_the_pin_covers_what_the_figures_depend_on_outside_ledgerql():
    for rel in (
        "evals/number_audit.py",
        "evals/NUMBER_AUDIT_SPEC.md",
        "evals/must_state.py",
        "evals/must_state_patterns.json",
        "evals/gold_v3.py",
        "evals/scoring.py",
        "docs/schema.md",  # the schema text of every prompt: read by ledgerql/, stored outside it
        "scripts/bridges2/run_model_eval.sh",
    ):
        assert rel in M.PINNED, rel
    # the stores that change after the pin are not in it, and neither is anything under ledgerql/
    assert not {"evals/measurement_pin.json", "evals/heldout_config.json", "uv.lock"} & set(
        M.PINNED
    )
    assert not [rel for rel in M.PINNED if rel.startswith("ledgerql/")]


def test_the_schema_text_the_pipeline_reads_is_the_file_that_is_pinned():
    from ledgerql import schema_index

    assert schema_index.SCHEMA_MD_PATH == M.REPO / "docs" / "schema.md"


def test_an_import_inside_a_function_counts(tmp_path):
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals/a.py").write_text("def f():\n    from evals import b\n    import evals.c\n")
    (tmp_path / "evals/b.py").write_text("from evals.d import x\n")
    (tmp_path / "evals/c.py").write_text("import json\n")
    (tmp_path / "evals/d.py").write_text("x = 1\n")
    (tmp_path / "evals/e.py").write_text("from evals import a\n")
    graph = M.evals_imports(tmp_path)
    assert M.import_closure(["evals/a.py"], graph) == {
        "evals/a.py",
        "evals/b.py",
        "evals/c.py",
        "evals/d.py",
    }


# --- the refusal ------------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path):
    """A small tree with two pinned files, a lock and a pin that matches them."""
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals/scorer.py").write_text("x = 1\n")
    (tmp_path / "evals/patterns.json").write_text("{}\n")
    (tmp_path / "uv.lock").write_text('[[package]]\nname = "duckdb"\nversion = "1.5.5"\n')
    pin = {
        "id": "M1",
        "status": "active",
        "files": M.file_hashes(["evals/scorer.py", "evals/patterns.json"], tmp_path),
        "environment": {
            "uv_lock_sha256": run_env.sha256_file(tmp_path / "uv.lock"),
            "locked": {"duckdb": "1.5.5"},
        },
    }
    return tmp_path, pin


HELDOUT, DEV = "evals/heldout_v1.jsonl", "evals/gold_v3.jsonl"


def test_a_heldout_run_is_refused_until_a_pin_is_recorded(repo):
    path, _ = repo
    with pytest.raises(FrozenGoldError, match="not pinned"):
        M.require_pinned(HELDOUT, pins=[], repo=path)
    M.require_pinned(DEV, pins=[], repo=path)  # any other gold file is never checked


def test_a_tree_that_matches_its_pin_has_no_problems(repo):
    path, pin = repo
    assert M.problems(pin, path, installed={"duckdb": "1.5.5"}) == []


def test_a_changed_or_missing_pinned_file_is_named(repo):
    path, pin = repo
    (path / "evals/scorer.py").write_text("x = 2\n")
    (path / "evals/patterns.json").unlink()
    assert M.problems(pin, path, installed={"duckdb": "1.5.5"}) == [
        "evals/patterns.json is pinned and does not exist",
        "evals/scorer.py differs from the pin",
    ]


def test_a_changed_lock_file_is_refused(repo):
    path, pin = repo
    (path / "uv.lock").write_text('[[package]]\nname = "duckdb"\nversion = "1.5.6"\n')
    assert M.problems(pin, path, installed={"duckdb": "1.5.5"}) == ["uv.lock differs from the pin"]


def test_an_environment_that_was_not_built_from_the_pinned_lock_is_refused(repo):
    # the lock file is byte-identical, and the installed engine is a different version
    path, pin = repo
    assert M.problems(pin, path, installed={"duckdb": "1.6.0"}) == [
        "duckdb 1.6.0 is installed and the pinned uv.lock names 1.5.5"
    ]
    assert "duckdb None is installed" in M.problems(pin, path, installed={})[0]


def test_the_refusal_names_the_pin_and_every_difference(repo, monkeypatch):
    path, pin = repo
    monkeypatch.setattr(run_env, "installed", lambda packages: {"duckdb": "1.5.5"})
    M.require_pinned(HELDOUT, pins=[pin], repo=path)  # matches: allowed
    (path / "evals/scorer.py").write_text("x = 2\n")
    (path / "uv.lock").write_text("")
    with pytest.raises(FrozenGoldError) as e:
        M.require_pinned(HELDOUT, pins=[pin], repo=path)
    assert "pin M1" in str(e.value)
    assert "evals/scorer.py differs" in str(e.value) and "uv.lock differs" in str(e.value)
    M.require_pinned(DEV, pins=[pin], repo=path)  # a development run is not held to the pin


def test_applying_records_the_tree_as_it_is_and_keeps_an_earlier_pin_as_superseded(
    repo, monkeypatch
):
    path, _ = repo
    monkeypatch.setattr(M, "PINNED", {"evals/scorer.py": "", "evals/patterns.json": ""})
    store = path / "measurement_pin.json"
    first = M.apply("MJ", "first", store, path)
    assert (
        first["id"] == "M1"
        and first["approved_by"] == "MJ"
        and set(first["files"]) == set(M.PINNED)
    )
    assert first["environment"]["locked"] == {"duckdb": "1.5.5", "sqlglot": None}
    assert M.problems(first, path, installed={"duckdb": "1.5.5", "sqlglot": None}) == []
    (path / "evals/scorer.py").write_text("x = 3\n")
    second = M.apply("MJ", "the scorer changed before any held-out run", store, path)
    pins = json.loads(store.read_text())
    assert [(p["id"], p["status"]) for p in pins] == [("M1", "superseded"), ("M2", "active")]
    assert pins[0]["superseded_by"] == "M2" and M.active_pin(pins)["id"] == second["id"]
    assert pins[0]["files"] != pins[1]["files"]


def test_a_file_that_does_not_exist_cannot_be_pinned(repo, monkeypatch):
    path, _ = repo
    monkeypatch.setattr(M, "PINNED", {"evals/gone.py": ""})
    with pytest.raises(ValueError, match="evals/gone.py"):
        M.apply("MJ", "why", path / "pin.json", path)
    assert not (path / "pin.json").exists()


# --- the repository ---------------------------------------------------------------------------


def test_both_live_entry_points_check_the_pin_after_the_freeze_and_the_configuration():
    for name in ("run_eval.py", "gen_only_eval.py"):
        text = (M.REPO / "evals" / name).read_text()
        frozen = text.index("scoring.require_frozen(args.gold)")
        declared = text.index("heldout_config.require_declared(")
        pinned = text.index("measurement_pin.require_pinned(args.gold)")
        assert frozen < declared < pinned, name


def test_the_recorded_pin_if_any_matches_the_working_tree():
    """No pin is recorded until the list is approved and the grader is settled. Once one is, a
    change to any pinned file or to uv.lock fails here, in CI, before it can reach a run."""
    pin = M.active_pin()
    if pin is None:
        assert not Path(M.PIN_PATH).exists()
        with pytest.raises(FrozenGoldError, match="not pinned"):
            M.require_pinned(HELDOUT)
        return
    assert M.problems(pin) == []
    assert set(pin["files"]) == set(M.PINNED)
