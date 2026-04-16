import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

# Check multiple paths: Docker mount (/models) or local dev (relative to repo root)
_MODELS_DIR = Path("/models") if Path("/models").exists() else Path(__file__).parent.parent.parent.parent / "models"


@router.get("/models")
async def list_models():
    """List available OpenSCAD 3D print model files."""
    if not _MODELS_DIR.exists():
        return []
    files = []
    for f in sorted(_MODELS_DIR.glob("*.scad")):
        files.append({
            "filename": f.name,
            "size_bytes": f.stat().st_size,
            "url": f"/api/builder/models/{f.name}",
        })
    return files


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
