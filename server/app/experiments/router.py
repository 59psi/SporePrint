from fastapi import APIRouter, HTTPException

from ..db import UnknownReferenceError
from .models import ExperimentCreate, ExperimentUpdate
from . import service

router = APIRouter()


@router.post("")
async def create_experiment(data: ExperimentCreate):
    try:
        return await service.create_experiment(data)
    except UnknownReferenceError as e:
        raise HTTPException(422, str(e))


@router.get("")
async def list_experiments(status: str | None = None):
    return await service.list_experiments(status)


@router.get("/{experiment_id}")
async def get_experiment(experiment_id: int):
    experiment = await service.get_experiment(experiment_id)
    if not experiment:
        raise HTTPException(404, "Experiment not found")
    return experiment


@router.patch("/{experiment_id}")
async def update_experiment(experiment_id: int, data: ExperimentUpdate):
    experiment = await service.update_experiment(experiment_id, data)
    if not experiment:
        raise HTTPException(404, "Experiment not found")
    return experiment


@router.get("/{experiment_id}/comparison")
async def get_comparison(experiment_id: int):
    comparison = await service.get_comparison(experiment_id)
    if not comparison:
        raise HTTPException(404, "Experiment not found")
    return comparison


@router.post("/{experiment_id}/analyze")
@router.get("/{experiment_id}/analyze", deprecated=True)  # older dashboard bundles call it
async def analyze_experiment(experiment_id: int):
    """Run a (paid) Claude analysis of the experiment. Only the POST is
    current — it is not a safe/idempotent read; the dashboard posts it. The
    GET (marked deprecated in the API schema) remains for older dashboard
    bundles: a server-only update leaves the bundle a Pi already serves. A
    page on another site can't trigger it either way
    (host_allow.CrossSiteRequestGuard)."""
    result = await service.analyze_experiment(experiment_id)
    if not result:
        raise HTTPException(404, "Experiment not found")
    return result
