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


class IntelligenceTier(int, Enum):
    """
    Ascending Intelligence Ladder (Level 0 -> Level 5):
    Use lowest intelligence tier capable of producing verifiable success.
    """
    DETERMINISTIC = 0   # Python, Z3, AST Grep, Compilers
    SYSTEM_ONE = 1      # tev1, nimble, bounded probabilistic choice
    E2B_WORKER = 2      # gemma4:e2b-it-qat (2.3B eff, 4.3 GB, 0 cost workhorse)
    E4B_ENGINEER = 3    # gemma4:e4b-it-qat (4.5B eff, 6.1 GB, local reasoning/repair)
    WORKSTATION = 4     # gemma4:12b/26b local heavy
    FRONTIER = 5        # Claude, Codex, Gemini 3.1 Pro (Metered API exception handler)


class CodeProvider(ABC):
    """Abstract provider adapter decoupling brand identity from role."""

    def __init__(
        self,
        provider_id: str,
        model_id: str,
        *,
        tier: IntelligenceTier = IntelligenceTier.FRONTIER,
    ) -> None:
        self.provider_id = provider_id
        self.model_id = model_id
        self.tier = tier

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

    def __init__(self, *, prefer_ascending_ladder: bool = True) -> None:
        self._providers: Dict[str, CodeProvider] = {}
        # Key: (provider_id, capability) -> CompetenceRecord
        self._competence: Dict[tuple, CompetenceRecord] = {}
        self.prefer_ascending_ladder = prefer_ascending_ladder

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

    def resolve(
        self,
        capability: Capability,
        task: TaskNode,
        *,
        min_tier: Optional[IntelligenceTier] = None,
    ) -> Optional[CodeProvider]:
        """
        Resolves optimal provider maximizing utility via the Ascending Intelligence Ladder.
        Prioritizes lowest adequate intelligence tier (E2B -> E4B -> Frontier)
        calibrated by empirical competence.
        """
        candidates = [
            p for p in self._providers.values()
            if p.declares_capability(capability)
            and (min_tier is None or p.tier >= min_tier)
        ]
        if not candidates:
            return None

        if self.prefer_ascending_ladder:
            # Sort by:
            # 1. Lower intelligence tier first (cheapest / zero-marginal compute)
            # 2. Higher expected competence within that tier
            # 3. Provider name as tie-breaker
            candidates.sort(
                key=lambda p: (
                    p.tier.value if isinstance(p.tier, IntelligenceTier) else int(p.tier),
                    -self.get_competence(p.provider_id, capability),
                    p.provider_id,
                )
            )
        else:
            # Traditional pure-competence sort
            candidates.sort(
                key=lambda p: (
                    -self.get_competence(p.provider_id, capability),
                    p.provider_id,
                )
            )
        return candidates[0]
