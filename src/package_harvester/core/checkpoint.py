"""
Checkpoint management for resumable harvesting.

Provides data structures for tracking harvest progress and enabling
crash recovery through JSON-serialized checkpoints.
"""

import time
from dataclasses import asdict, dataclass, field
from enum import Enum


class TaskStatus(Enum):
    """Status of a harvesting task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class HarvestTask:
    """Represents a single harvest task."""

    app_id: str
    pkg_name: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    last_error: str | None = None
    sources_fetched: list = field(default_factory=list)


@dataclass
class HarvestCheckpoint:
    """Checkpoint data for resumable harvesting."""

    total_tasks: int
    completed: int
    failed: int
    skipped: int
    last_updated: float
    tasks: dict[str, dict]  # app_id -> task dict

    @staticmethod
    def create(total_tasks: int) -> "HarvestCheckpoint":
        """Create a new empty checkpoint."""
        return HarvestCheckpoint(
            total_tasks=total_tasks,
            completed=0,
            failed=0,
            skipped=0,
            last_updated=time.time(),
            tasks={},
        )

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict (handling enums)."""
        data = asdict(self)
        for _app_id, task_data in data["tasks"].items():
            if isinstance(task_data.get("status"), TaskStatus):
                task_data["status"] = task_data["status"].value
        return data
