"""Core mission, intent, task graph, and lifecycle entities for NouGenCode."""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional, Set


class MissionState(str, Enum):
    RECEIVED = "RECEIVED"
    HYDRATING = "HYDRATING"
    MAPPED = "MAPPED"
    PLANNED = "PLANNED"
    CLAIMED = "CLAIMED"
    EXECUTING = "EXECUTING"
    VALIDATING = "VALIDATING"
    REVIEWING = "REVIEWING"
    ARBITRATING = "ARBITRATING"
    VERIFIED = "VERIFIED"
    COMPLETED = "COMPLETED"
    # Exceptional states
    BLOCKED = "BLOCKED"
    TIMED_OUT = "TIMED_OUT"
    NEEDS_REPLAN = "NEEDS_REPLAN"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    ROLLED_BACK = "ROLLED_BACK"
    ABANDONED = "ABANDONED"
    SUPERSEDED = "SUPERSEDED"


class Capability(str, Enum):
    CODE_SEARCH = "code_search"
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    DEBUGGING = "debugging"
    TEST_CREATION = "test_creation"
    TEST_RUNNER = "test_runner"
    STATIC_REVIEW = "static_review"
    SECURITY_REVIEW = "security_review"
    PERFORMANCE_REVIEW = "performance_review"
    PRODUCT_REVIEW = "product_review"
    VISUAL_REVIEW = "visual_review"
    REGRESSION_REVIEW = "regression_review"
    ARBITER = "arbiter"


@dataclass(frozen=True)
class RuntimeIdentity:
    """Resolved runtime identity strictly enforcing zero hardcoded paths, users, or nodes."""
    tenant_id: str
    workspace_id: str
    machine_id: str
    repo_id: str
    session_id: str
    branch: Optional[str] = None
    provider_id: Optional[str] = None
    agent_id: Optional[str] = None


@dataclass
class Intent:
    """Explicitly inferred and bounded specification."""
    goal: str
    acceptance: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    forbidden: List[str] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)


@dataclass
class MutationBudget:
    """Restraint contract bounding the allowable blast radius."""
    max_files: int = 5
    max_added_lines: int = 150
    max_deleted_lines: int = 100
    allowed_roots: List[str] = field(default_factory=list)
    forbidden_roots: List[str] = field(default_factory=list)

    def evaluate_drift(self, files_changed: int, lines_added: int, lines_deleted: int = 0) -> float:
        """Computes mutation drift ratio against budget."""
        file_drift = files_changed / max(1, self.max_files)
        added_drift = lines_added / max(1, self.max_added_lines)
        deleted_drift = lines_deleted / max(1, self.max_deleted_lines)
        return max(file_drift, added_drift, deleted_drift)


@dataclass
class TaskNode:
    """Node in the task execution DAG."""
    id: str
    objective: str
    dependencies: List[str] = field(default_factory=list)
    files_expected: List[str] = field(default_factory=list)
    capability: Capability = Capability.IMPLEMENTATION
    risk: float = 0.1
    mutation_budget: Optional[MutationBudget] = None
    validation: List[str] = field(default_factory=list)
    completed: bool = False
    attempted: bool = False
    execution_status: Optional[str] = None
    evidence: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CodeMission:
    """Unified execution mission object representing intent-to-verified transformation."""
    mission_id: str
    identity: RuntimeIdentity
    intent: Intent
    baseline_commit: str
    state: MissionState = MissionState.RECEIVED
    task_graph: List[TaskNode] = field(default_factory=list)
    claims: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    mutations: List[Dict[str, Any]] = field(default_factory=list)
    tests: List[Dict[str, Any]] = field(default_factory=list)
    token_cost: int = 0
    retries: int = 0
    created_at: float = field(default_factory=time.time)

    def ready_nodes(self) -> List[TaskNode]:
        """Returns nodes whose dependencies have all completed."""
        completed_ids = {t.id for t in self.task_graph if t.completed}
        return [
            t for t in self.task_graph
            if not t.completed and not t.attempted and all(dep in completed_ids for dep in t.dependencies)
        ]

    def task_graph_errors(self) -> List[str]:
        """Return deterministic structural errors before a provider can mutate the repo."""
        ids = [task.id for task in self.task_graph]
        errors: List[str] = []
        duplicates = sorted({task_id for task_id in ids if ids.count(task_id) > 1})
        if duplicates:
            errors.append("duplicate task ids: " + ", ".join(duplicates))
        known = set(ids)
        for task in self.task_graph:
            missing = sorted(set(task.dependencies) - known)
            if missing:
                errors.append(f"{task.id} has missing dependencies: " + ", ".join(missing))

        # Kahn's algorithm detects cycles without depending on input ordering.
        remaining = {task.id: set(task.dependencies) & known for task in self.task_graph}
        ready = sorted(task_id for task_id, deps in remaining.items() if not deps)
        visited: Set[str] = set()
        while ready:
            task_id = ready.pop(0)
            if task_id in visited:
                continue
            visited.add(task_id)
            for other_id in sorted(remaining):
                if task_id in remaining[other_id]:
                    remaining[other_id].remove(task_id)
                    if not remaining[other_id] and other_id not in visited:
                        ready.append(other_id)
                        ready.sort()
        cyclic = sorted(set(remaining) - visited)
        if cyclic:
            errors.append("task dependency cycle: " + ", ".join(cyclic))
        return errors
