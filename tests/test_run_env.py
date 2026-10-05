"""What a run ran on (evals/run_env.py): resolved versions beside the lock, read without ever
failing the run."""

import json
import sys

from evals import run_env as E


def test_the_environment_the_tests_run_in_is_the_one_uv_lock_names():
    # The figures depend on the SQL parser and the engine. If this fails, the environment was not
    # built from uv.lock, and a figure computed in it is not attributable to the lock.
    installed, locked = E.installed(), E.locked()
    assert set(installed) == set(locked) == {"duckdb", "sqlglot"}
    assert all(locked.values()) and installed == locked


def test_a_package_that_is_not_installed_or_not_locked_reads_as_none(tmp_path):
    assert E.installed(("no-such-package-xyz",)) == {"no-such-package-xyz": None}
    assert E.locked(("no-such-package-xyz",)) == {"no-such-package-xyz": None}
    assert E.locked(("duckdb",), tmp_path / "missing.lock") == {"duckdb": None}
    lock = tmp_path / "uv.lock"
    lock.write_text('[[package]]\nname = "duckdb"\nversion = "9.9.9"\n')
    assert E.locked(("duckdb", "sqlglot"), lock) == {"duckdb": "9.9.9", "sqlglot": None}


def test_a_file_hash_is_of_its_bytes_and_a_missing_file_has_none(tmp_path):
    f = tmp_path / "f"
    f.write_bytes(b"abc")
    assert E.sha256_file(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert E.sha256_file(tmp_path / "missing") is None and E.sha256_file(tmp_path) is None


def test_the_servers_versions_are_read_by_its_own_interpreter():
    got = E.server_versions(sys.executable, packages=("duckdb", "no-such-package-xyz"))
    assert got["duckdb"] == E.installed(("duckdb",))["duckdb"]
    assert got["no-such-package-xyz"] is None and got["python"].count(".") == 2
    assert got["interpreter"] == sys.executable


def test_reading_the_server_never_raises():
    assert "unavailable" in E.server_versions(None)
    broken = E.server_versions("/no/such/python")
    assert "unavailable" in broken and broken["interpreter"] == "/no/such/python"
    assert "unavailable" in E.server_versions(sys.executable, timeout=0.000001)


def test_the_record_is_one_json_object_with_settings_as_set_or_unset(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("OLLAMA_SEED", "7")
    monkeypatch.delenv("LEDGERQL_ROW_LIMIT", raising=False)
    db = tmp_path / "db"
    db.write_bytes(b"abc")
    assert E.main(["--server-python", sys.executable, "--db", str(db)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {
        "python",
        "packages",
        "locked",
        "uv_lock_sha256",
        "server",
        "settings",
        "database_sha256",
    }
    assert out["settings"]["OLLAMA_SEED"] == "7" and out["settings"]["LEDGERQL_ROW_LIMIT"] is None
    assert out["uv_lock_sha256"] == E.sha256_file(E.LOCK_PATH) and len(out["uv_lock_sha256"]) == 64
    assert out["database_sha256"].startswith("ba7816bf")
    assert set(out["server"]) >= {"vllm", "transformers", "torch"}
