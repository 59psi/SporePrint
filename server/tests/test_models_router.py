"""Builder model downloads: lib/ inlining, listing, traversal guards, bundle ZIP.

Two groups:

* Synthetic models dir (tmp_path) on a bare FastAPI app with only the models
  router mounted — exercises the inliner's edge cases (nesting, dedupe,
  cycles, depth, missing files, commented-out includes, escapes/symlinks).
* The real repo `models/` — every shipped model flattens to a file with no
  include statement left and, when a working OpenSCAD is available, renders
  on its own from a temp dir that has NO lib/ folder, producing the same STL
  bytes as the original rendered next to its lib/.

OpenSCAD is found via $SPOREPRINT_OPENSCAD (or $OPENSCAD_BIN), then
`openscad` on PATH, then the macOS app bundle; render tests skip when none
of those actually runs.
"""

import io
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.builder import models_router as mr

_REPO_MODELS = Path(__file__).resolve().parents[2] / "models"
_STATEMENT_RE = re.compile(r"^\s*(include|use)\s*<([^>]*)>")


# ── helpers ─────────────────────────────────────────────────────


def _code_lines(text: str) -> list[str]:
    """Lines that start outside a /* */ comment, with any // tail removed."""
    lines = []
    in_block = False
    for line in text.splitlines():
        starts_in_block = in_block
        in_block = mr._block_comment_after(line, in_block)
        if not starts_in_block:
            lines.append(line.split("//", 1)[0])
    return lines


def _statements(text: str) -> list[tuple[str, str]]:
    """Every live `include <...>` / `use <...>` statement as (kind, path)."""
    return [(m[1], m[2]) for line in _code_lines(text) if (m := _STATEMENT_RE.match(line))]


def _app_client() -> TestClient:
    app = FastAPI()
    app.include_router(mr.router, prefix="/api/builder")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def models_dir(tmp_path, monkeypatch):
    """Point the router at an empty tmp models/ (+ lib/) and reset its cache."""
    root = tmp_path / "models"
    (root / "lib").mkdir(parents=True)
    monkeypatch.setattr(mr, "_MODELS_DIR", root)
    monkeypatch.setattr(mr, "_models_cache", {"data": [], "ts": 0})
    return root


@pytest.fixture
def api():
    return _app_client()


@pytest.fixture
def repo_models(monkeypatch):
    assert _REPO_MODELS.is_dir(), _REPO_MODELS
    monkeypatch.setattr(mr, "_MODELS_DIR", _REPO_MODELS)
    monkeypatch.setattr(mr, "_models_cache", {"data": [], "ts": 0})
    return _REPO_MODELS


def _repo_model_names() -> list[str]:
    return sorted(p.name for p in _REPO_MODELS.glob("*.scad"))


# ── inlining (synthetic) ────────────────────────────────────────


def test_download_inlines_lib_include(models_dir, api):
    (models_dir / "lib" / "a.scad").write_text("A_CONST = 3;\nfunction a_f() = A_CONST;\n")
    (models_dir / "part.scad").write_text(
        "// header\ninclude <lib/a.scad>\ncube(a_f());\n")

    r = api.get("/api/builder/models/part.scad")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert 'filename="part.scad"' in r.headers["content-disposition"]
    body = r.text
    assert "// ── inlined from lib/a.scad ──\nA_CONST = 3;\n" in body
    assert "// ── end of inlined lib/a.scad ──\ncube(a_f());\n" in body
    assert body.startswith("// header\n")
    assert _statements(body) == []
    assert "include <lib/" not in body


def test_inlines_nested_lib_includes_once(models_dir, api):
    lib = models_dir / "lib"
    # Inside lib/, OpenSCAD resolves a bare name relative to lib/ itself.
    (lib / "a.scad").write_text("include <b.scad>\nA = B + 1;\n")
    (lib / "b.scad").write_text("B = 1;")  # no trailing newline on purpose
    (models_dir / "part.scad").write_text(
        "include <lib/a.scad>\ninclude <lib/b.scad>;  // again\ncube(A);\n")

    body = api.get("/api/builder/models/part.scad").text
    assert _statements(body) == []
    assert body.count("B = 1;") == 1
    assert body.count("── inlined from lib/b.scad ──") == 1
    assert "// ── lib/b.scad already inlined above ──" in body
    # b is nested inside a's block, in source order.
    assert (body.index("inlined from lib/a.scad")
            < body.index("inlined from lib/b.scad")
            < body.index("end of inlined lib/b.scad")
            < body.index("A = B + 1;")
            < body.index("end of inlined lib/a.scad"))


def test_commented_out_includes_are_left_alone(models_dir, api):
    (models_dir / "lib" / "a.scad").write_text("A = 1;\n")
    src = ("// include <lib/a.scad>\n"
           "/* disabled:\n"
           "include <lib/a.scad>\n"
           "*/\n"
           "x = \"/* not a comment\";\n"
           "cube(1);\n")
    (models_dir / "part.scad").write_text(src)
    assert api.get("/api/builder/models/part.scad").text == src


def test_include_cycle_is_rejected(models_dir, api):
    lib = models_dir / "lib"
    (lib / "a.scad").write_text("include <b.scad>\n")
    (lib / "b.scad").write_text("include <a.scad>\n")
    (models_dir / "part.scad").write_text("include <lib/a.scad>\n")

    r = api.get("/api/builder/models/part.scad")
    assert r.status_code == 500
    assert "cycle" in r.json()["detail"]


def test_include_depth_limit(models_dir, api):
    lib = models_dir / "lib"
    depth = mr._INLINE_MAX_DEPTH + 2
    for i in range(depth):
        nxt = f"include <l{i + 1}.scad>\n" if i + 1 < depth else ""
        (lib / f"l{i}.scad").write_text(f"{nxt}L{i} = {i};\n")
    (models_dir / "part.scad").write_text("include <lib/l0.scad>\n")

    r = api.get("/api/builder/models/part.scad")
    assert r.status_code == 500
    assert "deeper" in r.json()["detail"]


def test_depth_at_limit_is_fine(models_dir, api):
    lib = models_dir / "lib"
    depth = mr._INLINE_MAX_DEPTH
    for i in range(depth):
        nxt = f"include <l{i + 1}.scad>\n" if i + 1 < depth else ""
        (lib / f"l{i}.scad").write_text(f"{nxt}L{i} = {i};\n")
    (models_dir / "part.scad").write_text("include <lib/l0.scad>\n")

    r = api.get("/api/builder/models/part.scad")
    assert r.status_code == 200
    assert _statements(r.text) == []
    assert f"L{depth - 1} = {depth - 1};" in r.text


def test_missing_lib_file_is_an_error(models_dir, api):
    (models_dir / "part.scad").write_text("include <lib/nope.scad>\ncube(1);\n")
    r = api.get("/api/builder/models/part.scad")
    assert r.status_code == 500
    assert "lib/nope.scad" in r.json()["detail"]


def test_only_files_inside_lib_are_inlined(models_dir, api, tmp_path):
    secret = tmp_path / "secret.scad"
    secret.write_text("SECRET = 42;\n")
    (models_dir / "other.scad").write_text("OTHER = 1;\n")
    (models_dir / "lib" / "evil.scad").symlink_to(secret)
    src = ("include <other.scad>\n"
           "include <../secret.scad>\n"
           "include <lib/../../secret.scad>\n"
           f"include <{secret}>\n"
           "include <lib/evil.scad>\n"
           "include <MCAD/units.scad>\n")
    (models_dir / "part.scad").write_text(src)

    r = api.get("/api/builder/models/part.scad")
    assert r.status_code == 200
    # Nothing outside models/lib/ is read; the lines stay verbatim.
    assert r.text == src
    assert "SECRET = 42" not in r.text
    assert "OTHER = 1" not in r.text


# ── listing / traversal (synthetic) ─────────────────────────────


def test_listing_excludes_lib(models_dir, api):
    (models_dir / "lib" / "sp_inserts.scad").write_text("X = 1;\n")
    (models_dir / "b_part.scad").write_text("cube(1);\n")
    (models_dir / "a_part.scad").write_text("cube(1);\n")
    (models_dir / "README.md").write_text("# models\n")

    r = api.get("/api/builder/models")
    assert r.status_code == 200
    body = r.json()
    assert [m["filename"] for m in body] == ["a_part.scad", "b_part.scad"]
    for m in body:
        assert m["size_bytes"] == 9
        assert m["url"] == f"/api/builder/models/{m['filename']}"
        # No header comment: the title falls back to the stem.
        assert m["title"] == m["filename"][:-5]
        assert m["description"] == ""
        assert m["source_url"] == f"{mr.MODELS_REPO_URL.replace('/tree/', '/blob/')}/{m['filename']}"


def test_listing_reads_title_and_description_from_the_header(models_dir, api):
    (models_dir / "widget.scad").write_text(
        "// SporePrint Widget Holder\n"
        "// Two printed pieces joined by\n"
        "// 4 x M3 heat-set inserts.\n"
        "//\n"
        "// ── FITS ──\n"
        "cube(1);\n"
    )
    (m,) = api.get("/api/builder/models").json()
    assert m["title"] == "Widget Holder"
    assert m["description"] == "Two printed pieces joined by 4 x M3 heat-set inserts."


def test_every_shipped_model_has_a_title_and_description():
    # The Builder's Models tab renders these; a model without a summary
    # paragraph shows up blank.
    for f in sorted((mr._REPO_ROOT / "models").glob("*.scad")):
        title, description = mr._model_header(f)
        assert title and title != f.stem, f.name
        assert len(description) >= 40, (f.name, description)
        assert not description[0].islower(), (f.name, description)


def test_models_repo_url_points_at_the_models_directory():
    assert mr.MODELS_REPO_URL == "https://github.com/59psi/SporePrint/tree/main/models"
    assert (mr._REPO_ROOT / "models").is_dir()


@pytest.mark.parametrize("path", [
    "/api/builder/models/..%2Fsecret.scad",
    "/api/builder/models/..%2F..%2Fetc%2Fpasswd",
    "/api/builder/models/lib%2Fsp_inserts.scad",
    "/api/builder/models/lib/sp_inserts.scad",
    "/api/builder/models/..",
    "/api/builder/models/lib",
    "/api/builder/models/sp_inserts.scad",   # lib file is not a top-level model
    "/api/builder/models/README.md",
    "/api/builder/models/missing.scad",
    "/api/builder/models/a..scad",
])
def test_traversal_and_non_models_rejected(models_dir, api, tmp_path, path):
    (tmp_path / "secret.scad").write_text("SECRET = 42;\n")
    (models_dir / "lib" / "sp_inserts.scad").write_text("X = 1;\n")
    (models_dir / "README.md").write_text("# models\n")
    r = api.get(path)
    assert r.status_code in (400, 404), (path, r.status_code)
    assert "SECRET" not in r.text


def test_symlinked_model_outside_models_dir_rejected(models_dir, api, tmp_path):
    outside = tmp_path / "outside.scad"
    outside.write_text("SECRET = 42;\n")
    (models_dir / "link.scad").symlink_to(outside)
    r = api.get("/api/builder/models/link.scad")
    assert r.status_code == 404
    assert "SECRET" not in r.text


# ── bundle (synthetic) ──────────────────────────────────────────


def test_bundle_contains_models_lib_and_readme(models_dir, api, tmp_path):
    (models_dir / "lib" / "a.scad").write_text("A = 1;\n")
    (models_dir / "lib" / "sub").mkdir()
    (models_dir / "lib" / "sub" / "c.scad").write_text("C = 1;\n")
    (models_dir / "lib" / "notes.txt").write_text("not scad\n")
    (models_dir / "part.scad").write_text("include <lib/a.scad>\ncube(A);\n")
    (models_dir / "README.md").write_text("# models\n")
    (tmp_path / "secret.scad").write_text("SECRET = 42;\n")
    (models_dir / "lib" / "evil.scad").symlink_to(tmp_path / "secret.scad")

    r = api.get("/api/builder/models-bundle.zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert 'filename="sporeprint-models.zip"' in r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(zf.namelist()) == [
        "sporeprint-models/README.md",
        "sporeprint-models/lib/a.scad",
        "sporeprint-models/lib/sub/c.scad",
        "sporeprint-models/part.scad",
    ]
    # Bundle keeps the repo layout, so the original include line is kept.
    assert zf.read("sporeprint-models/part.scad") == b"include <lib/a.scad>\ncube(A);\n"


def test_bundle_route_does_not_collide_with_model_route(models_dir, api):
    (models_dir / "models-bundle.zip.scad").write_text("cube(1);\n")
    assert api.get("/api/builder/models-bundle.zip").headers["content-type"] == "application/zip"
    assert api.get("/api/builder/models/models-bundle.zip").status_code == 404


# ── the real repo models ────────────────────────────────────────


def test_repo_models_have_no_sibling_includes():
    """Single-file downloads only work if models include nothing but lib/."""
    offenders = []
    for path in sorted(_REPO_MODELS.glob("*.scad")) + sorted((_REPO_MODELS / "lib").rglob("*.scad")):
        for kind, target in _statements(path.read_text(encoding="utf-8")):
            in_lib = path.parent != _REPO_MODELS
            ok = kind == "include" and (not in_lib and target.startswith("lib/")
                                        or in_lib and "/" not in target)
            if not ok:
                offenders.append(f"{path.relative_to(_REPO_MODELS)}: {kind} <{target}>")
    assert offenders == []


def test_repo_listing_is_top_level_only(repo_models, api):
    names = [m["filename"] for m in api.get("/api/builder/models").json()]
    assert names == _repo_model_names()
    lib_names = {p.name for p in (repo_models / "lib").glob("*.scad")}
    assert lib_names  # sp_inserts.scad etc. exist …
    assert not lib_names & set(names)  # … but are not listed as models


@pytest.mark.parametrize("name", _repo_model_names())
def test_repo_model_download_is_self_contained(repo_models, api, name):
    original = (repo_models / name).read_text(encoding="utf-8")
    wanted = sorted({t for k, t in _statements(original) if k == "include"})

    r = api.get(f"/api/builder/models/{name}")
    assert r.status_code == 200
    body = r.text
    assert _statements(body) == []
    # Any literal "include <lib/" left is prose inside a // comment (the
    # lib headers document this very mechanism), never code.
    for line in body.splitlines():
        if "include <lib/" in line:
            assert line.lstrip().startswith("//"), line
    for target in wanted:
        assert body.count(f"// ── inlined from {target} ──") == 1
        assert body.count(f"// ── end of inlined {target} ──") == 1
        lib_src = (repo_models / target).read_text(encoding="utf-8")
        assert lib_src in body
    if not wanted:
        assert body == original


def test_repo_bundle_contents(repo_models, api):
    zf = zipfile.ZipFile(io.BytesIO(api.get("/api/builder/models-bundle.zip").content))
    names = set(zf.namelist())
    expected = {f"sporeprint-models/{n}" for n in _repo_model_names()}
    expected |= {f"sporeprint-models/lib/{p.relative_to(repo_models / 'lib').as_posix()}"
                 for p in (repo_models / "lib").rglob("*.scad")}
    expected.add("sporeprint-models/README.md")
    assert names == expected
    assert {"sporeprint-models/lib/sp_inserts.scad",
            "sporeprint-models/lib/pi5_dims.scad",
            "sporeprint-models/lib/sensor_mount_dims.scad"} <= names
    for n in _repo_model_names():
        assert zf.read(f"sporeprint-models/{n}") == (repo_models / n).read_bytes()


def test_routes_mounted_in_real_app(client):
    """The full app serves both endpoints under /api/builder (no shadowing)."""
    r = client.get("/api/builder/models-bundle.zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    r = client.get("/api/builder/models/pi_case.scad")
    assert r.status_code == 200
    assert "// ── inlined from lib/pi5_dims.scad ──" in r.text
    assert _statements(r.text) == []


# ── standalone render with native OpenSCAD ──────────────────────


def _find_openscad() -> str | None:
    candidates = [os.environ.get("SPOREPRINT_OPENSCAD"), os.environ.get("OPENSCAD_BIN"),
                  shutil.which("openscad"),
                  "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"]
    for cand in candidates:
        if not cand or not Path(cand).exists():
            continue
        try:
            res = subprocess.run([cand, "--version"], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            continue  # e.g. a wrong-architecture Homebrew build
        if res.returncode == 0:
            return cand
    return None


@pytest.fixture(scope="module")
def openscad():
    exe = _find_openscad()
    if exe is None:
        pytest.skip("no working OpenSCAD (set SPOREPRINT_OPENSCAD)")
    help_text = subprocess.run([exe, "--help"], capture_output=True, text=True, timeout=60)
    manifold = "--backend" in (help_text.stdout + help_text.stderr)
    return [exe] + (["--backend=Manifold"] if manifold else [])


def _render(cmd: list[str], scad: Path, stl: Path) -> tuple[int, str]:
    res = subprocess.run(cmd + ["-o", str(stl), str(scad)],
                         capture_output=True, text=True, timeout=600, cwd=scad.parent)
    return res.returncode, res.stdout + res.stderr


def _problems(log: str) -> list[str]:
    return [ln for ln in log.splitlines()
            if re.search(r"\b(WARNING|ERROR)\b", ln) and "NoError" not in ln]


@pytest.mark.parametrize("name", _repo_model_names())
def test_downloaded_model_renders_without_lib(repo_models, api, openscad, tmp_path, name):
    flat_dir = tmp_path / "download"   # no lib/ folder here
    flat_dir.mkdir()
    flat = flat_dir / name
    flat.write_bytes(api.get(f"/api/builder/models/{name}").content)
    assert not (flat_dir / "lib").exists()

    rc, log = _render(openscad, flat, tmp_path / "flat.stl")
    assert rc == 0, log
    assert _problems(log) == [], log

    # Same geometry as the original rendered next to its lib/.
    rc0, log0 = _render(openscad, repo_models / name, tmp_path / "orig.stl")
    assert rc0 == 0, log0
    assert (tmp_path / "flat.stl").read_bytes() == (tmp_path / "orig.stl").read_bytes()

    # Control: the un-inlined original, alone in a dir without lib/, cannot
    # find its includes, which shows the flat render above needed no lib/.
    if _statements((repo_models / name).read_text(encoding="utf-8")):
        bare_dir = tmp_path / "bare"
        bare_dir.mkdir()
        shutil.copy(repo_models / name, bare_dir / name)
        _rc1, log1 = _render(openscad, bare_dir / name, tmp_path / "bare.stl")
        assert re.search(r"Can't (open|find) include file '?lib/", log1), log1
