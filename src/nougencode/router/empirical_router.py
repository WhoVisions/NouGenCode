"""
Empirical Posterior Provider Router.

Implements the NouGenCode routing optimization:
    P* = argmax_{p in P} [ alpha*Q_p(T) + beta*H_p(T) + gamma*R_p(C) + delta*M_p
                           - lambda_1*Cost_p - lambda_2*Latency_p - lambda_3*FailureRisk_p ]

And posterior belief updates:
    theta_{p,t}^{(n+1)} = theta_{p,t}^{(n)} + eta * (Outcome_n - ExpectedOutcome_n)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from nougencode.discovery.waterflow import ProviderCapability
from nougencode.roles.contracts import EngineeringRole


@dataclass
class TaskSpecification:
    role: EngineeringRole
    language: str = "python"
    estimated_tokens: int = 2000
    is_mutation_heavy: bool = False
    urgency: str = "normal"  # "low", "normal", "high"


@dataclass
class ProviderPerformancePosterior:
    provider_id: str
    role: EngineeringRole
    historical_quality_score: float = 0.80  # theta_{p, t}
    total_runs: int = 0
    failures_observed: int = 0
    mean_latency_ms: float = 250.0


class EmpiricalProviderRouter:
    """Dynamically resolves the best available provider for each role based on evidence."""

    def __init__(
        self,
        learning_rate_eta: float = 0.10,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.eta = learning_rate_eta
        self.weights = weights or {
            "alpha_quality": 0.40,
            "beta_hardware": 0.20,
            "gamma_repo": 0.15,
            "lambda_cost": 0.15,
            "lambda_latency": 0.10,
        }
        self.posteriors: Dict[Tuple[str, EngineeringRole], ProviderPerformancePosterior] = {}

    def get_or_create_posterior(self, provider_id: str, role: EngineeringRole) -> ProviderPerformancePosterior:
        key = (provider_id, role)
        if key not in self.posteriors:
            self.posteriors[key] = ProviderPerformancePosterior(provider_id=provider_id, role=role)
        return self.posteriors[key]

    def update_posterior(
        self,
        provider_id: str,
        role: EngineeringRole,
        observed_outcome: float,  # 1.0 = touchdown, 0.0 = test failure/rejection
    ) -> None:
        """Bayesian belief update: theta^{(n+1)} = theta^{(n)} + eta * (Outcome - Expected)."""
        post = self.get_or_create_posterior(provider_id, role)
        expected = post.historical_quality_score
        error = observed_outcome - expected
        post.historical_quality_score = max(0.01, min(0.99, post.historical_quality_score + self.eta * error))
        post.total_runs += 1
        if observed_outcome < 0.5:
            post.failures_observed += 1

    def resolve_provider(
        self,
        task: TaskSpecification,
        available_providers: Dict[str, ProviderCapability],
    ) -> Tuple[Optional[ProviderCapability], float]:
        """Compute P* score and return optimal provider."""
        best_provider: Optional[ProviderCapability] = None
        best_score = float("-inf")

        for pid, prov in available_providers.items():
            if not prov.is_available:
                continue
            if task.role.value not in prov.supported_roles:
                continue

            post = self.get_or_create_posterior(pid, task.role)

            # Cost penalty
            cost_penalty = 0.0 if prov.cost_tier == "zero_marginal" else (0.50 if prov.cost_tier == "metered_api" else 1.0)

            # Latency penalty
            lat_penalty = 0.10 if prov.latency_profile == "fast" else (0.40 if prov.latency_profile == "medium" else 0.80)

            # Failure risk
            failure_risk = post.failures_observed / max(1, post.total_runs)

            score = (
                self.weights["alpha_quality"] * post.historical_quality_score
                + self.weights["beta_hardware"] * 0.90
                - self.weights["lambda_cost"] * cost_penalty
                - self.weights["lambda_latency"] * lat_penalty
                - 0.20 * failure_risk
            )

            if score > best_score:
                best_score = score
                best_provider = prov

        return best_provider, best_score
