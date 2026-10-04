"""The README may only point at what the repository has.

It once advertised an API server and a UI that were never built, and the Makefile had targets
that ran them. So: every relative link, every file or directory path, every `make` target and
every first-party Python module the README names must exist, and every Makefile target must run
something that exists. "Exists" means in a fresh clone (tracked, or new and not ignored), which
is what CI and a reader have; a path that is built locally is declared in `BUILT` with the target
that builds it.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Paths that are not in a clone because a Makefile target builds them: path -> that target.
BUILT = {"data/ledgerql.duckdb": "data"}

_EXTENSIONS = "md|py|json|jsonl|toml|yml|yaml|sh|sbatch|txt|csv|duckdb|lock|sha256"
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.M | re.S)
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
# `dir/file.ext`, `dir/sub/`, or a bare `FILE.ext`: no spaces, no wildcards, no <placeholders>.
_PATH = re.compile(rf"(?:[\w.-]+/)+[\w.-]*|[\w-][\w.-]*\.(?:{_EXTENSIONS})")
_PATH_IN_TEXT = re.compile(r"(?<![\w./<$-])[\w.-]+(?:/[\w.-]+)+/?(?![\w/>*])")
_MAKE = re.compile(r"\bmake\s+([a-z][\w.-]*)")
_TARGET = re.compile(r"^([A-Za-z0-9_.-]+):(?!=)", re.M)
_IMPORT = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+([\w, ]+)", re.M)


def repo_files(root: Path = ROOT) -> set[str]:
    """Every path a fresh clone of the working tree would have."""
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return set(listed.stdout.splitlines())


def _has(path: str, files: set[str]) -> bool:
    path = path.removeprefix("./").rstrip("/")
    return path in files or any(f.startswith(path + "/") for f in files)


def _paths_in_code(code: str, files: set[str]) -> set[str]:
    """Slash-joined tokens in a command or a diagram that are meant as paths: the ones that end in
    a file extension or start in one of the repository's own directories. `tables/columns` in a
    diagram is neither."""
    tops = {f.split("/")[0] for f in files if "/" in f}
    return {
        p
        for p in _PATH_IN_TEXT.findall(code)
        if p.split("/")[0] in tops or re.search(rf"\.(?:{_EXTENSIONS})$", p)
    }


def _module_file(module: str, files: set[str]) -> str | None:
    base = module.replace(".", "/")
    return next((f for f in (base + ".py", base + "/__init__.py") if f in files), None)


def _first_party(files: set[str]) -> str:
    packages = sorted({f.split("/")[0] for f in files if f.endswith("/__init__.py")})
    return "|".join(map(re.escape, packages)) or "(?!)"


def _missing_modules(code: str, files: set[str], where: str) -> list[str]:
    """First-party modules written as `pkg.mod` (after `python -m`, in an import, as `pkg.mod:app`)
    that no file defines."""
    dotted = re.compile(rf"(?<![\w/.-])((?:{_first_party(files)})(?:\.[A-Za-z_]\w*)+)")
    return [
        f"{where}: module `{m}` does not exist"
        for m in sorted(set(dotted.findall(code)))
        if _module_file(m, files) is None
    ]


def makefile_targets(makefile: str) -> set[str]:
    return {t for t in _TARGET.findall(makefile) if not t.startswith(".")}


def makefile_problems(makefile: str, files: set[str]) -> list[str]:
    """A target declared phony that is not defined, or a recipe that runs a first-party module or
    a file the repository does not have."""
    targets = makefile_targets(makefile)
    problems = [
        f"Makefile: .PHONY names `{name}`, which is not a target"
        for line in re.findall(r"^\.PHONY:(.*)$", makefile, re.M)
        for name in line.split()
        if name not in targets
    ]
    recipes = "\n".join(line for line in makefile.splitlines() if line.startswith("\t"))
    problems += _missing_modules(recipes, files, "Makefile")
    for path in sorted(_paths_in_code(recipes, files)):
        if not _has(path, files) and BUILT.get(path) not in targets:
            problems.append(f"Makefile: `{path}` does not exist")
    return problems


def readme_problems(readme: str, makefile: str, files: set[str]) -> list[str]:
    """Everything the README names that the repository does not have."""
    targets = makefile_targets(makefile)
    fences = _FENCE.findall(readme)
    prose = _FENCE.sub("", readme)
    spans = _CODE_SPAN.findall(prose)
    code = "\n".join([*fences, *spans])

    paths = {
        link.split("#")[0]
        for link in _LINK.findall(prose)
        if not re.match(r"[a-z][a-z0-9+.-]*:|#", link)
    }
    paths |= {s for s in spans if _PATH.fullmatch(s)}
    paths |= {p for block in fences for p in _paths_in_code(block, files)}
    problems = []
    for path in sorted(paths - {""}):
        if _has(path, files):
            continue
        if path in BUILT:
            if BUILT[path] not in targets:
                problems.append(f"README: `{path}` is built by a target that does not exist")
            continue
        problems.append(f"README: `{path}` does not exist")
    for target in sorted(set(_MAKE.findall(code))):
        if target not in targets:
            problems.append(f"README: `make {target}` is not a Makefile target")
    problems += _missing_modules(code, files, "README")
    for module, names in _IMPORT.findall(code):
        source = _module_file(module, files)
        if source is None:
            continue  # reported above, or not ours
        text = (ROOT / source).read_text() if (ROOT / source).exists() else ""
        for name in (n.strip() for n in names.split(",")):
            if name and not re.search(rf"^(?:def|class)\s+{name}\b|^{name}\s*[:=]", text, re.M):
                problems.append(f"README: `{module}` does not define `{name}`")
    return problems


# --- the checker itself -----------------------------------------------------------------------

_FILES = {"README.md", "Makefile", "pkg/__init__.py", "pkg/core.py", "docs/guide.md", "run.sh"}
_MAKEFILE = ".PHONY: test data\n\ntest:\n\tpytest\n\ndata:\n\tpython -m pkg.core\n"


def test_a_link_a_path_or_a_directory_the_repo_has_is_fine():
    readme = (
        "See [the guide](docs/guide.md#setup), `pkg/core.py`, `pkg/`, `run.sh` and `README.md`."
    )
    assert readme_problems(readme, _MAKEFILE, _FILES) == []


def test_a_link_or_a_path_to_nothing_is_reported():
    readme = (
        "See [the API](pkg/api.py), `pkg/ui/app.py` and `NOTES.md`.\n```bash\nsh tools/x.sh\n```\n"
    )
    assert readme_problems(readme, _MAKEFILE, _FILES) == [
        "README: `NOTES.md` does not exist",
        "README: `pkg/api.py` does not exist",
        "README: `pkg/ui/app.py` does not exist",
        "README: `tools/x.sh` does not exist",
    ]


def test_web_links_anchors_placeholders_and_plain_code_are_not_paths():
    readme = (
        "[site](https://example.com/a/b) [below](#limits) `reports/runs/<job>` `evals/*.py` "
        "`SELECT a/b FROM t` `qwen2.5-coder:7b` `10-K` `ask()` [licence](./run.sh)\n"
        "```\n[2] schema retrieval (relevant tables/columns)\n```\n"
    )
    assert readme_problems(readme, _MAKEFILE, _FILES) == []
    # but a slash-joined token in a code block that starts in one of the repo's directories is one
    assert readme_problems("```\ncat docs/missing\n```\n", _MAKEFILE, _FILES) == [
        "README: `docs/missing` does not exist"
    ]


def test_a_make_target_the_makefile_does_not_have_is_reported():
    readme = "Run `make test`, then:\n```bash\nmake data\nmake api   # the server\n```\n"
    assert readme_problems(readme, _MAKEFILE, _FILES) == [
        "README: `make api` is not a Makefile target"
    ]
    assert readme_problems("We make sure and make data clean.", _MAKEFILE, _FILES) == []  # prose


def test_a_module_or_a_name_the_code_does_not_have_is_reported():
    readme = (
        "```python\nfrom pkg.core import ask\nfrom pkg.api import app\n```\n`python -m pkg.cli`"
    )
    assert readme_problems(readme, _MAKEFILE, _FILES) == [
        "README: module `pkg.api` does not exist",
        "README: module `pkg.cli` does not exist",
        "README: `pkg.core` does not define `ask`",  # pkg/core.py is not on disk here
    ]


def test_a_built_path_is_allowed_only_while_its_target_exists():
    readme = "`make data` builds `data/ledgerql.duckdb`."
    assert readme_problems(readme, _MAKEFILE, _FILES) == []
    assert readme_problems(readme, "test:\n\tpytest\n", _FILES) == [
        "README: `data/ledgerql.duckdb` is built by a target that does not exist",
        "README: `make data` is not a Makefile target",
    ]


def test_a_makefile_target_that_runs_something_missing_is_reported():
    # the three targets this repository had: a server and a UI that were never built
    dead = (
        ".PHONY: test run api ui gone\n\ntest:\n\tpytest\n\n"
        "api:\n\tuv run uvicorn pkg.api:app --reload\n\n"
        "ui:\n\tuv run streamlit run pkg/ui/app.py\n\nrun: api\n"
    )
    assert makefile_problems(dead, _FILES) == [
        "Makefile: .PHONY names `gone`, which is not a target",
        "Makefile: module `pkg.api` does not exist",
        "Makefile: `pkg/ui/app.py` does not exist",
    ]
    assert makefile_problems(_MAKEFILE, _FILES) == []


# --- the repository ---------------------------------------------------------------------------


def test_the_readme_names_only_what_the_repository_has():
    files = repo_files()
    readme, makefile = (ROOT / "README.md").read_text(), (ROOT / "Makefile").read_text()
    assert readme_problems(readme, makefile, files) == []


def test_every_makefile_target_runs_something_that_exists():
    assert makefile_problems((ROOT / "Makefile").read_text(), repo_files()) == []


def test_the_check_reads_the_readme_it_is_meant_to():
    """Guards the guard: if the patterns stopped matching, an empty list would mean nothing."""
    readme = (ROOT / "README.md").read_text()
    prose = _FENCE.sub("", readme)
    assert len(_LINK.findall(prose)) >= 20
    assert set(_MAKE.findall("\n".join(_FENCE.findall(readme)))) >= {"setup", "test", "data"}
    assert "ledgerql.pipeline" in "\n".join(_FENCE.findall(readme))
