import time
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

_MODELS_DIR = Path("/models") if Path("/models").exists() else Path(__file__).parent.parent.parent.parent / "models"
_DOCS_DIR = Path("/docs") if Path("/docs").exists() else Path(__file__).parent.parent.parent.parent / "docs"

_models_cache: dict = {"data": [], "ts": 0}
_diagrams_cache: dict = {"data": [], "ts": 0}
_CACHE_TTL = 60  # seconds


def _cached_list(directory: Path, suffix: str, cache: dict) -> list[dict]:
    now = time.time()
    if now - cache["ts"] < _CACHE_TTL and cache["data"]:
        return cache["data"]
    if not directory.exists():
        cache["data"] = []
    else:
        url_segment = "models" if suffix == ".scad" else "diagrams"
        cache["data"] = [
            {"filename": f.name, "size_bytes": f.stat().st_size, "url": f"/api/builder/{url_segment}/{f.name}"}
            for f in sorted(directory.glob(f"*{suffix}"))
        ]
    cache["ts"] = now
    return cache["data"]


@router.get("/models")
async def list_models():
    """List available OpenSCAD 3D print model files."""
    return _cached_list(_MODELS_DIR, ".scad", _models_cache)


@router.get("/models/{filename}")
async def download_model(filename: str):
    """Download an OpenSCAD model file."""
    # Sanitize filename to prevent path traversal
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    filepath = _MODELS_DIR / safe_name
    if not filepath.exists() or not filepath.suffix == ".scad":
        raise HTTPException(404, "Model not found")
    return FileResponse(str(filepath), media_type="text/plain",
                        headers={"Content-Disposition": f"attachment; filename={safe_name}"})


@router.get("/diagrams")
async def list_diagrams():
    """List available SVG wiring and architecture diagrams."""
    return _cached_list(_DOCS_DIR, ".svg", _diagrams_cache)


@router.get("/diagrams/{filename}")
async def get_diagram(filename: str):
    """Serve an SVG diagram."""
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    filepath = _DOCS_DIR / safe_name
    if not filepath.exists() or filepath.suffix != ".svg":
        raise HTTPException(404, "Diagram not found")
    return FileResponse(str(filepath), media_type="image/svg+xml")
