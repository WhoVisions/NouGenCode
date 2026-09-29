"""
Waterflow Environment & Provider Discovery Engine.

Dynamically discovers local execution environment, hardware capabilities, installed
runtimes, coding CLIs (Claude, Codex, Gemini, AGY), local endpoints (Ollama, LM Studio),
and repositories without any hardcoded user or machine paths.
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class HardwareProfile:
    os_name: str
    architecture: str
    cpu_cores: int
    has_gpu: bool
    gpu_type: str = "cpu"
    total_ram_gb: float = 0.0


@dataclass
class ProviderCapability:
    provider_id: str
    name: str
    kind: str  # "local_cli", "local_daemon", "cloud_api"
    executable_path: Optional[str] = None
    endpoint_url: Optional[str] = None
    is_available: bool = False
    supported_roles: List[str] = field(default_factory=list)
    cost_tier: str = "free"  # "zero_marginal", "metered_api", "subscription"
    latency_profile: str = "medium"  # "fast", "medium", "slow"


@dataclass
class EnvironmentSnapshot:
    hardware: HardwareProfile
    discovered_providers: Dict[str, ProviderCapability]
    discovered_repositories: List[str]
    has_docker: bool = False
    has_git: bool = False


class WaterflowDiscovery:
    """Universal, zero-hardcoding environment and provider scanner."""

    @staticmethod
    def inspect_hardware() -> HardwareProfile:
        os_name = platform.system().lower()
        arch = platform.machine()
        cores = os.cpu_count() or 4

        has_gpu = False
        gpu_type = "cpu"
        if os_name == "darwin":
            # Apple Silicon Unified Memory
            has_gpu = True
            gpu_type = "apple_metal"
        elif shutil.which("nvidia-smi"):
            has_gpu = True
            gpu_type = "nvidia_cuda"

        return HardwareProfile(
            os_name=os_name,
            architecture=arch,
            cpu_cores=cores,
            has_gpu=has_gpu,
            gpu_type=gpu_type,
        )

    @classmethod
    def check_daemon(cls, host: str, port: int, timeout: float = 0.3) -> bool:
        """Non-blocking socket check for active local inference engines."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (OSError, ConnectionRefusedError):
            return False

    @classmethod
    def discover_providers(cls) -> Dict[str, ProviderCapability]:
        providers: Dict[str, ProviderCapability] = {}

        # 1. Local Tier 0 Daemons (Ollama / LM Studio)
        ollama_live = cls.check_daemon("127.0.0.1", 11434)
        providers["ollama"] = ProviderCapability(
            provider_id="ollama",
            name="Ollama Local Daemon",
            kind="local_daemon",
            endpoint_url="http://127.0.0.1:11434",
            is_available=ollama_live,
            supported_roles=["BUILDER", "TESTER", "REPAIR"],
            cost_tier="zero_marginal",
            latency_profile="fast",
        )

        lm_studio_live = cls.check_daemon("127.0.0.1", 1234)
        providers["lm_studio"] = ProviderCapability(
            provider_id="lm_studio",
            name="LM Studio Local Daemon",
            kind="local_daemon",
            endpoint_url="http://127.0.0.1:1234",
            is_available=lm_studio_live,
            supported_roles=["BUILDER", "CRITIC"],
            cost_tier="zero_marginal",
            latency_profile="fast",
        )

        # 2. Local Coding CLIs
        claude_path = shutil.which("claude")
        providers["claude_code"] = ProviderCapability(
            provider_id="claude_code",
            name="Claude Code CLI",
            kind="local_cli",
            executable_path=claude_path,
            is_available=bool(claude_path),
            supported_roles=["ARCHITECT", "BUILDER", "REVIEWER"],
            cost_tier="metered_api",
            latency_profile="medium",
        )

        codex_path = shutil.which("codex")
        providers["codex_cli"] = ProviderCapability(
            provider_id="codex_cli",
            name="OpenAI Codex CLI",
            kind="local_cli",
            executable_path=codex_path,
            is_available=bool(codex_path),
            supported_roles=["BUILDER", "REPAIR", "TESTER"],
            cost_tier="metered_api",
            latency_profile="fast",
        )

        agy_path = shutil.which("agy")
        providers["antigravity_cli"] = ProviderCapability(
            provider_id="antigravity_cli",
            name="Google Antigravity CLI",
            kind="local_cli",
            executable_path=agy_path,
            is_available=bool(agy_path),
            supported_roles=["ARCHITECT", "ARBITER", "SECURITY"],
            cost_tier="metered_api",
            latency_profile="fast",
        )

        return providers

    @classmethod
    def discover_environment(cls, search_root: Optional[Path] = None) -> EnvironmentSnapshot:
        hw = cls.inspect_hardware()
        provs = cls.discover_providers()
        has_git = bool(shutil.which("git"))
        has_docker = bool(shutil.which("docker"))

        # Discover repositories from current working context outwards
        repos: List[str] = []
        root = search_root or Path.cwd()
        if (root / ".git").is_dir():
            repos.append(str(root))

        return EnvironmentSnapshot(
            hardware=hw,
            discovered_providers=provs,
            discovered_repositories=repos,
            has_docker=has_docker,
            has_git=has_git,
        )
