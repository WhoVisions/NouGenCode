"""
Comprehensive test suite verifying NouGenCode architecture.
"""

from __future__ import annotations

from dataclasses import fields
import pytest

from nougencode.discovery.waterflow import WaterflowDiscovery
from nougencode.roles.contracts import ROLE_REGISTRY, EngineeringRole, RoleContract
from nougencode.router.empirical_router import EmpiricalProviderRouter, TaskSpecification
from nougencode.security.invariants import ConcentricSecurityGate


def test_waterflow_hardware_and_provider_discovery():
    hw = WaterflowDiscovery.inspect_hardware()
    assert hw.os_name in ("darwin", "linux", "windows")
    assert hw.cpu_cores >= 1

    providers = WaterflowDiscovery.discover_providers()
    assert "ollama" in providers
    assert "codex_cli" in providers
    assert "claude_code" in providers
    assert "antigravity_cli" in providers


def test_engineering_role_contracts():
    contract_fields = {field.name for field in fields(RoleContract)}
    assert not contract_fields.intersection({"provider_id", "provider_name", "model_id"})
    for role in EngineeringRole:
        contract = ROLE_REGISTRY.get(role)
        assert contract is not None
        assert contract.role == role
        assert len(contract.required_capabilities) > 0


def test_empirical_posterior_routing_and_bayesian_updates():
    router = EmpiricalProviderRouter()
    providers = WaterflowDiscovery.discover_providers()

    # Force simulated availability for testing
    providers["ollama"].is_available = True
    providers["codex_cli"].is_available = True

    task = TaskSpecification(role=EngineeringRole.BUILDER)

    # Initial resolution
    chosen, score = router.resolve_provider(task, providers)
    assert chosen is not None

    # Simulate 5 successful runs for codex
    for _ in range(5):
        router.update_posterior("codex_cli", EngineeringRole.BUILDER, 1.0)

    # Simulate 5 failures for ollama
    for _ in range(5):
        router.update_posterior("ollama", EngineeringRole.BUILDER, 0.0)

    # Posteriors must reflect evidence
    codex_post = router.get_or_create_posterior("codex_cli", EngineeringRole.BUILDER)
    ollama_post = router.get_or_create_posterior("ollama", EngineeringRole.BUILDER)
    assert codex_post.historical_quality_score > ollama_post.historical_quality_score


def test_concentric_security_gate():
    # Clean code passes
    clean_code = "import os\npath = os.path.expanduser('~/.nougen')\nprint('hello')"
    ConcentricSecurityGate.assert_clean(clean_code)

    # Leak credentials fails
    dirty_cred = "api_key = 'sk-123456789012345678901234567890'"
    with pytest.raises(ValueError, match="CREDENTIAL_EXPOSURE"):
        ConcentricSecurityGate.assert_clean(dirty_cred)

    # Leak personal path fails
    dirty_path = "root = '/Users/dave/Projects/secret'"
    with pytest.raises(ValueError, match="PERSONAL_PATH_LEAK"):
        ConcentricSecurityGate.assert_clean(dirty_path)
