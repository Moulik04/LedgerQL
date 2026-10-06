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

SERVER = {"vllm": "0.29.0", "transformers": "4.57.1", "torch": "2.11.0+cu126"}
LOCK = '[[package]]\nname = "duckdb"\nversion = "1.5.5"\n'


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A small tree with two pinned files, a lock, a database, the server's setup script, and a
    pin that matches them. The model server reads as the pinned one unless a test says otherwise."""
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals/scorer.py").write_text("x = 1\n")
    (tmp_path / "evals/patterns.json").write_text("{}\n")
    (tmp_path / "uv.lock").write_text(LOCK)
    (tmp_path / "db.duckdb").write_bytes(b"the database")
    (tmp_path / "scripts/bridges2").mkdir(parents=True)
    (tmp_path / "scripts/bridges2/setup_env.sh").write_text("set -e\nVLLM_VERSION=0.29.0\n")
    pin = {
        "id": "M1",
        "status": "active",
        "files": M.file_hashes(["evals/scorer.py", "evals/patterns.json"], tmp_path),
        "environment": {
            "uv_lock_sha256": run_env.sha256_file(tmp_path / "uv.lock"),
            "locked": {"duckdb": "1.5.5"},
            "database_sha256": run_env.sha256_file(tmp_path / "db.duckdb"),
            "server": dict(SERVER),
        },
        "settings": json.loads(json.dumps(M.SETTINGS)),
    }
    monkeypatch.setattr(run_env, "installed", lambda packages: {"duckdb": "1.5.5"})
    monkeypatch.setattr(
        run_env, "server_versions", lambda python: {"interpreter": python, **SERVER}
    )
    return tmp_path, pin


HELDOUT, DEV = "evals/heldout_v1.jsonl", "evals/gold_v3.jsonl"


def _settings(mode="pipeline", **changed):
    """What a run of `mode` reports when it runs as declared: the first declared model."""
    declared = M.SETTINGS[mode]
    return {**{k: v[0] if isinstance(v, list) else v for k, v in declared.items()}, **changed}


def _require(gold, pin, path, mode="pipeline", environ=None, **changed):
    M.require_pinned(
        gold,
        mode=mode,
        settings=_settings(mode, **changed),
        db=path / "db.duckdb",
        server_python="/venv/bin/python",
        pins=[] if pin is None else [pin],
        repo=path,
        environ={} if environ is None else environ,
    )


def test_a_heldout_run_is_refused_until_a_pin_is_recorded(repo):
    path, _ = repo
    with pytest.raises(FrozenGoldError, match="not pinned"):
        _require(HELDOUT, None, path)
    _require(DEV, None, path)  # any other gold file is never checked


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


def test_a_database_that_is_not_the_pinned_one_is_refused(repo):
    path, pin = repo
    assert M.problems(pin, path, db=path / "db.duckdb") == []
    (path / "db.duckdb").write_bytes(b"the database, rebuilt")
    assert M.problems(pin, path, db=path / "db.duckdb") == [
        f"the database {path / 'db.duckdb'} differs from the pin"
    ]
    assert M.problems(pin, path, db=path / "gone.duckdb") == [
        f"the database {path / 'gone.duckdb'} does not exist"
    ]
    assert M.problems(pin, path) == []  # asked without a database, the tree alone is compared


def test_a_model_server_on_other_versions_is_refused(repo):
    path, pin = repo
    assert M.problems(pin, path, server=dict(SERVER)) == []
    assert M.problems(pin, path, server={**SERVER, "vllm": "0.30.1", "torch": None}) == [
        "the model server has torch None and the pin names 2.11.0+cu126",
        "the model server has vllm 0.30.1 and the pin names 0.29.0",
    ]


def test_a_model_server_whose_versions_cannot_be_read_is_refused(repo):
    path, pin = repo
    unread = {"unavailable": "no server interpreter was given"}
    assert M.problems(pin, path, server=unread) == [
        "the model server's versions could not be read (no server interpreter was given)"
    ]


def test_a_setting_exported_by_the_submitting_shell_is_refused():
    assert M.override_problems({"PATH": "/bin", "LEDGERQL_ENTITY_LINK": "1"}) == []
    found = M.override_problems({"OLLAMA_SEED": "42", "LEDGERQL_ROW_LIMIT": "50"})
    assert len(found) == 2 and "OLLAMA_SEED is set in the environment ('42')" in found[1]
    # every variable that overrides a default is covered; the linker's is checked against H
    assert {name for name in run_env.SETTINGS if M.override_problems({name: "x"})} == set(
        run_env.SETTINGS
    ) - {"LEDGERQL_ENTITY_LINK"}


@pytest.mark.parametrize(
    "mode, changed",
    [
        ("pipeline", {"model": "Qwen/Qwen2.5-Coder-7B-Instruct"}),
        ("pipeline", {"backend": "ollama"}),
        ("pipeline", {"seed": 7}),
        ("pipeline", {"candidates": 3}),
        ("pipeline", {"consensus_temperature": 1.0}),
        ("pipeline", {"temperature": 0.0}),
        ("pipeline", {"entity_link": False}),
        ("gen_only", {"model": "Qwen/Qwen2.5-Coder-7B-Instruct"}),
        ("gen_only", {"seed": 7}),
        ("gen_only", {"candidates": 10}),
        ("gen_only", {"temperature": 0.2}),
        ("gen_only", {"max_tokens": 512}),
    ],
)
def test_a_generation_setting_that_differs_from_the_declaration_is_refused(mode, changed):
    assert M.settings_problems(M.SETTINGS, mode, _settings(mode)) == []
    (name, value), declared = next(iter(changed.items())), M.SETTINGS[mode]
    assert M.settings_problems(M.SETTINGS, mode, _settings(mode, **changed)) == [
        f"{name} is {value!r} and the declared {mode} setting is {declared[name]!r}"
    ]


def test_every_declared_model_is_accepted_and_a_setting_the_run_does_not_report_is_refused():
    for mode, declared in M.SETTINGS.items():
        for model in declared["model"]:
            assert M.settings_problems(M.SETTINGS, mode, _settings(mode, model=model)) == []
    silent = {k: v for k, v in _settings("gen_only").items() if k != "max_tokens"}
    assert M.settings_problems(M.SETTINGS, "gen_only", silent) == [
        "max_tokens is None and the declared gen_only setting is 2048"
    ]


def test_the_declared_settings_restate_h3_where_h3_speaks():
    from evals import heldout_config

    h, p = heldout_config.active(), M.SETTINGS["pipeline"]
    assert p["model"] == [h["models"]["primary"], h["models"]["policy_partner"]]
    assert (p["candidates"], p["consensus_temperature"], p["seed"]) == (
        h["settings"]["candidates"],
        h["settings"]["consensus_temperature"],
        h["settings"]["seed"],
    )
    assert p["entity_link"] is (h["entity_link"]["decision"] == "on")


def _in_a_clean_shell(code: str, **exported) -> dict:
    """Run `code` with none of the override variables set, as a job does when nothing was
    exported, and return the JSON it prints."""
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k not in run_env.SETTINGS}
    done = subprocess.run(
        [sys.executable, "-c", code],
        env={**env, **exported},
        cwd=M.REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout)


def test_the_declared_settings_are_what_the_code_runs_with_when_nothing_is_exported():
    pipeline = _in_a_clean_shell(
        "import json; from evals import run_eval\nprint(json.dumps(run_eval.heldout_settings()))",
        LLM_BACKEND="vllm",
        OLLAMA_MODEL=M.SETTINGS["pipeline"]["model"][0],
        LEDGERQL_ENTITY_LINK="1",
    )
    assert M.settings_problems(M.SETTINGS, "pipeline", pipeline) == []
    gen_only = _in_a_clean_shell(
        "import json; from evals import gen_only_eval as G\n"
        "args = G.parser().parse_args(['--profile', 'omnisql', '--out', 'x', '--model', "
        f"{M.SETTINGS['gen_only']['model'][0]!r}])\n"
        "print(json.dumps(G.heldout_settings(args)))"
    )
    assert M.settings_problems(M.SETTINGS, "gen_only", gen_only) == []


def test_an_exported_seed_reaches_what_the_run_reports_so_it_cannot_pass_unseen():
    pipeline = _in_a_clean_shell(
        "import json; from evals import run_eval\nprint(json.dumps(run_eval.heldout_settings()))",
        OLLAMA_SEED="7",
        OLLAMA_CONSENSUS_TEMPERATURE="1.0",
    )
    assert (pipeline["seed"], pipeline["consensus_temperature"]) == (7, 1.0)
    assert pipeline["entity_link"] is False and pipeline["backend"] == "ollama"


def test_the_declared_models_are_the_ones_the_pinned_job_files_serve():
    served = {"pipeline": set(), "gen_only": set()}
    for rel in M.PINNED:
        if rel.endswith(".sbatch"):
            text = (M.REPO / rel).read_text()
            mode = "gen_only" if "export EVAL_MODE=gen_only" in text else "pipeline"
            served[mode].add(text.split("run_model_eval.sh ")[-1].split()[0])
    assert served == {mode: set(d["model"]) for mode, d in M.SETTINGS.items()}


def test_the_refusal_names_the_pin_and_every_difference(repo, monkeypatch):
    path, pin = repo
    _require(HELDOUT, pin, path)  # matches: allowed
    _require(HELDOUT, pin, path, mode="gen_only")
    (path / "evals/scorer.py").write_text("x = 2\n")
    (path / "uv.lock").write_text("")
    (path / "db.duckdb").write_bytes(b"another database")
    monkeypatch.setattr(run_env, "server_versions", lambda python: {**SERVER, "vllm": "0.30.1"})
    with pytest.raises(FrozenGoldError) as e:
        _require(HELDOUT, pin, path, environ={"OLLAMA_TEMPERATURE": "0.9"}, seed=7)
    said = str(e.value)
    assert "pin M1" in said
    for part in (
        "evals/scorer.py differs",
        "uv.lock differs",
        "db.duckdb differs from the pin",
        "the model server has vllm 0.30.1",
        "OLLAMA_TEMPERATURE is set in the environment",
        "seed is 7 and the declared pipeline setting is 42",
    ):
        assert part in said, part
    _require(DEV, pin, path, seed=7)  # a development run is not held to the pin


def test_the_server_is_read_through_the_interpreter_the_run_names(repo, monkeypatch):
    path, pin = repo
    asked = []
    monkeypatch.setattr(run_env, "server_versions", lambda python: asked.append(python) or SERVER)
    _require(HELDOUT, pin, path)
    assert asked == ["/venv/bin/python"]


# --- recording a pin --------------------------------------------------------------------------


def _cluster(path, **changed):
    """What `python -m evals.run_env --server-python ... --db ...` prints on the cluster."""
    return {
        "python": "3.13.7",
        "packages": {"duckdb": "1.5.5", "sqlglot": None},
        "locked": {"duckdb": "1.5.5", "sqlglot": None},
        "uv_lock_sha256": run_env.sha256_file(path / "uv.lock"),
        "server": {"interpreter": "/venv/bin/python", "python": "3.13.7", **SERVER},
        "settings": {},
        "database_sha256": run_env.sha256_file(path / "db.duckdb"),
        **changed,
    }


def _apply(path, why="first", **changed):
    return M.apply(
        "MJ", why, _cluster(path, **changed), path / "pin.json", path, db=path / "db.duckdb"
    )


def test_applying_records_the_tree_as_it_is_and_keeps_an_earlier_pin_as_superseded(
    repo, monkeypatch
):
    path, _ = repo
    monkeypatch.setattr(M, "PINNED", {"evals/scorer.py": "", "evals/patterns.json": ""})
    first = _apply(path)
    assert (
        first["id"] == "M1"
        and first["approved_by"] == "MJ"
        and set(first["files"]) == set(M.PINNED)
    )
    assert first["environment"]["locked"] == {"duckdb": "1.5.5", "sqlglot": None}
    assert M.problems(first, path, installed={"duckdb": "1.5.5", "sqlglot": None}) == []
    (path / "evals/scorer.py").write_text("x = 3\n")
    second = _apply(path, "the scorer changed before any held-out run")
    pins = json.loads((path / "pin.json").read_text())
    assert [(p["id"], p["status"]) for p in pins] == [("M1", "superseded"), ("M2", "active")]
    assert pins[0]["superseded_by"] == "M2" and M.active_pin(pins)["id"] == second["id"]
    assert pins[0]["files"] != pins[1]["files"]


def test_a_pin_records_the_server_the_database_and_the_settings_from_the_cluster_record(
    repo, monkeypatch
):
    path, _ = repo
    monkeypatch.setattr(M, "PINNED", {"evals/scorer.py": ""})
    pin = _apply(path)
    env = pin["environment"]
    assert env["server"] == SERVER  # the three packages, not the interpreter's path
    assert env["database_sha256"] == run_env.sha256_file(path / "db.duckdb")
    assert env["cluster_record"] == _cluster(path)  # kept whole, as it was read
    assert pin["settings"] == M.SETTINGS
    _require(HELDOUT, pin, path)


@pytest.mark.parametrize(
    "changed, said",
    [
        ({"uv_lock_sha256": "0" * 64}, "the cluster's uv.lock is not this tree's"),
        (
            {"packages": {"duckdb": "1.6.0", "sqlglot": None}},
            "the cluster's eval environment has",
        ),
        (
            {"server": {"unavailable": "FileNotFoundError"}},
            "no version for the model server's vllm",
        ),
        ({"server": {**SERVER, "transformers": None}}, "the model server's transformers"),
        ({"server": {**SERVER, "vllm": "0.30.1"}}, "setup_env.sh installs 0.29.0"),
        ({"database_sha256": None}, "does not state the database's hash"),
        ({"database_sha256": "0" * 64}, "the cluster's database is not the local one"),
    ],
)
def test_a_cluster_record_that_disagrees_with_this_tree_is_not_pinned(
    repo, monkeypatch, changed, said
):
    path, _ = repo
    monkeypatch.setattr(M, "PINNED", {"evals/scorer.py": ""})
    with pytest.raises(ValueError, match=said):
        _apply(path, **changed)
    assert not (path / "pin.json").exists()


def test_a_pin_needs_a_local_database_to_compare_the_clusters_with(repo, monkeypatch):
    path, _ = repo
    monkeypatch.setattr(M, "PINNED", {"evals/scorer.py": ""})
    with pytest.raises(ValueError, match="no local database"):
        M.apply("MJ", "why", _cluster(path), path / "pin.json", path, db=path / "gone.duckdb")


def test_a_file_that_does_not_exist_cannot_be_pinned(repo, monkeypatch):
    path, _ = repo
    monkeypatch.setattr(M, "PINNED", {"evals/gone.py": ""})
    with pytest.raises(ValueError, match="evals/gone.py"):
        _apply(path)
    assert not (path / "pin.json").exists()


# --- the offline figure commands --------------------------------------------------------------


def test_an_offline_command_runs_freely_until_a_pin_exists_and_then_only_on_a_matching_tree(repo):
    path, pin = repo
    db = path / "db.duckdb"
    M.require_unchanged(db, pins=[], repo=path)  # no pin yet: development work is not held
    M.require_unchanged(db, pins=[pin], repo=path)
    (path / "evals/scorer.py").write_text("x = 2  # not committed\n")
    with pytest.raises(FrozenGoldError, match="pin M1.*evals/scorer.py differs"):
        M.require_unchanged(db, pins=[pin], repo=path)


def test_an_offline_command_is_refused_on_another_database_or_another_engine(repo, monkeypatch):
    path, pin = repo
    (path / "other.duckdb").write_bytes(b"a fixture")
    with pytest.raises(FrozenGoldError, match="other.duckdb differs from the pin"):
        M.require_unchanged(path / "other.duckdb", pins=[pin], repo=path)
    monkeypatch.setattr(run_env, "installed", lambda packages: {"duckdb": "1.6.0"})
    with pytest.raises(FrozenGoldError, match="duckdb 1.6.0 is installed"):
        M.require_unchanged(path / "db.duckdb", pins=[pin], repo=path)
    with pytest.raises(FrozenGoldError, match="duckdb 1.6.0 is installed"):
        M.require_unchanged(pins=[pin], repo=path)  # a command that opens no database


def test_every_offline_figure_command_checks_the_pin_before_it_reads_anything():
    assert set(M.OFFLINE_COMMANDS) <= set(M.PINNED)
    for rel, check in M.OFFLINE_COMMANDS.items():
        text = (M.REPO / rel).read_text()
        body = text[text.index("def main(") :]
        assert check in body, rel
        parsed = body.index("args = ap.parse_args(argv)")
        assert body[parsed:].split("\n", 2)[1].strip() == check, rel  # the first thing main does


def test_every_pinned_command_that_reads_stored_records_is_an_offline_command_or_says_why_not():
    with_a_main = {
        rel
        for rel in M.PINNED
        if rel.startswith("evals/") and rel.endswith(".py")
        if "def main(" in (M.REPO / rel).read_text()
    }
    live = {"evals/run_eval.py", "evals/gen_only_eval.py"}
    assert with_a_main - live == set(M.OFFLINE_COMMANDS) | set(M.NOT_OFFLINE_COMMANDS)
    assert all(len(why) > 20 for why in M.NOT_OFFLINE_COMMANDS.values())


def test_figure_1_is_not_computed_on_a_tree_that_differs_from_the_pin(repo, monkeypatch):
    from evals import audit_vs_verify

    path, pin = repo
    (path / "evals/scorer.py").write_text("x = 2\n")
    monkeypatch.setattr(M, "active_pin", lambda pins=None: pin)
    monkeypatch.setattr(M, "REPO", path)
    monkeypatch.setattr(
        audit_vs_verify, "compare_runs", lambda *a, **k: pytest.fail("no figure is computed")
    )
    with pytest.raises(FrozenGoldError, match="evals/scorer.py differs"):
        audit_vs_verify.main(["--db", str(path / "db.duckdb")])


# --- the repository ---------------------------------------------------------------------------


def test_both_live_entry_points_check_the_pin_after_the_freeze_and_the_configuration():
    for name, mode in (("run_eval.py", "pipeline"), ("gen_only_eval.py", "gen_only")):
        text = (M.REPO / "evals" / name).read_text()
        frozen = text.index("scoring.require_frozen(args.gold)")
        declared = text.index("heldout_config.require_declared(")
        pinned = text.index("measurement_pin.require_pinned(")
        assert frozen < declared < pinned, name
        call = text[pinned : text.index("\n    )\n", pinned)]
        for given in (
            "args.gold",
            f'mode="{mode}"',
            "settings=heldout_settings(",
            "db=args.db",
            "server_python=args.server_python",
        ):
            assert given in call, (name, given)


def test_the_recorded_pin_if_any_matches_the_working_tree():
    """No pin is recorded until the grader is settled. Once one is, a change to any pinned file
    or to uv.lock fails here, in CI, before it can reach a run. The database and the model server
    are not in CI: a run checks those where they are."""
    pin = M.active_pin()
    if pin is None:
        assert not Path(M.PIN_PATH).exists()
        with pytest.raises(FrozenGoldError, match="not pinned"):
            M.require_pinned(
                HELDOUT, mode="pipeline", settings={}, db="data/ledgerql.duckdb", server_python=None
            )
        return
    assert M.problems(pin) == []
    assert set(pin["files"]) == set(M.PINNED)
    assert pin["settings"] == M.SETTINGS
    assert pin["environment"]["server"]["vllm"] == M.setup_vllm_version()


def test_the_server_setup_script_names_the_version_the_dev_runs_used():
    assert M.setup_vllm_version() == "0.29.0"  # job 47412929's server log (docs/bridges2.md)
