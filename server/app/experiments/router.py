from fastapi import APIRouter, HTTPException

from .models import ExperimentCreate, ExperimentUpdate
from . import service

router = APIRouter()


@router.post("")
async def create_experiment(data: ExperimentCreate):
    return await service.create_experiment(data)


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
