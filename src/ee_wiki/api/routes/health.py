"""Health check route."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ee_wiki.api.concurrency import RequestQueueGate
from ee_wiki.api.deps import get_queue_gate

router = APIRouter(tags=["health"])


@router.get("/health")
def health(gate: RequestQueueGate = Depends(get_queue_gate)) -> dict[str, object]:
    """Return liveness status and RAG queue visibility."""
    snapshot = gate.snapshot()
    return {
        "status": "ok",
        "queue": {
            "active": snapshot.active,
            "waiting": snapshot.waiting,
            "max_concurrent": snapshot.max_concurrent,
            "max_queue_depth": snapshot.max_queue_depth,
            "capacity": snapshot.capacity,
            "capacity_remaining": snapshot.capacity_remaining,
        },
    }
