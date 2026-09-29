"""Provider routing, role registry, and dynamic competency calibration."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import math
import time
from typing import Any, Dict, List, Optional

from nougencode.core.mission import Capability, TaskNode


class ExecutionStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    STALL = "STALL"
    INFRA_ERROR = "INFRA_ERROR"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass
class ProviderResult:
    status: ExecutionStatus
    output: str = ""
    mutations: List[Dict[str, Any]] = field(default_factory=list)
    latency_ms: int = 0
    tokens_used: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class CodeProvider(ABC):
    """Abstract provider adapter decoupling brand identity from role."""

    def __init__(self, provider_id: str, model_id: str) -> None:
        self.provider_id = provider_id
        self.model_id = model_id

    @abstractmethod
    def declares_capability(self, capability: Capability) -> bool:
        """Dynamically check if this provider supports the requested capability."""
        pass

    @abstractmethod
    async def execute(self, task: TaskNode, context: Dict[str, Any]) -> ProviderResult:
        """Execute a task under bounded context."""
        pass


@dataclass
class CompetenceRecord:
    alpha: float = 1.0  # Success prior
    beta: float = 1.0   # Failure prior

    @property
    def expected_competence(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    def record_outcome(self, success: bool) -> None:
        if success:
            self.alpha += 1.0
        else:
            self.beta += 1.0


class Switchboard:
    """Dynamic router mapping task roles to providers via calibrated competence."""

    def __init__(self) -> None:
        self._providers: Dict[str, CodeProvider] = {}
        # Key: (provider_id, capability) -> CompetenceRecord
        self._competence: Dict[tuple, CompetenceRecord] = {}

    def register_provider(self, provider: CodeProvider) -> None:
        self._providers[provider.provider_id] = provider

    def record_competence(self, provider_id: str, capability: Capability, success: bool) -> None:
        key = (provider_id, capability)
        if key not in self._competence:
            self._competence[key] = CompetenceRecord()
        self._competence[key].record_outcome(success)

    def get_competence(self, provider_id: str, capability: Capability) -> float:
        key = (provider_id, capability)
        if key not in self._competence:
            return 0.5  # Neutral uncalibrated prior
        return self._competence[key].expected_competence

    def resolve(self, capability: Capability, task: TaskNode) -> Optional[CodeProvider]:
        """Resolves optimal provider maximizing utility without brand preference."""
        candidates = [
            p for p in self._providers.values()
            if p.declares_capability(capability)
        ]
        if not candidates:
            return None

        # Provider names only break ties; Python's hash is process-randomized.
        candidates.sort(key=lambda provider: (-self.get_competence(provider.provider_id, capability), provider.provider_id))
        return candidates[0]
