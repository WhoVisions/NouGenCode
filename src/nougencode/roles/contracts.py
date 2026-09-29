"""
Roles as Capability Contracts, Not UI Buttons.

Roles:
- ARCHITECT: System design, invariant contracts, dependency mapping.
- BUILDER: Concrete file synthesis, implementation loops.
- CRITIC: AST deadcode scanning, code smell detection, design review.
- TESTER: Test suite execution, regression validation.
- SECURITY: Secret perimeter, permission boundary, blast-radius audit.
- REVIEWER: Pre-commit diff hygiene, documentation sync.
- REPAIR: Surgical error recovery and stack-trace resolution.
- ARBITER: Merge decisions, consensus tie-breaking, touchdown verification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


class EngineeringRole(str, Enum):
    ARCHITECT = "ARCHITECT"
    BUILDER = "BUILDER"
    CRITIC = "CRITIC"
    TESTER = "TESTER"
    SECURITY = "SECURITY"
    REVIEWER = "REVIEWER"
    REPAIR = "REPAIR"
    ARBITER = "ARBITER"


@dataclass(frozen=True)
class RoleContract:
    role: EngineeringRole
    required_capabilities: Set[str]
    max_mutation_scope: str  # "none", "scoped_files", "full_workspace"
    requires_sandbox: bool
    requires_human_gate: bool = False
    description: str = ""


ROLE_REGISTRY: Dict[EngineeringRole, RoleContract] = {
    EngineeringRole.ARCHITECT: RoleContract(
        role=EngineeringRole.ARCHITECT,
        required_capabilities={"deep_reasoning", "repo_mapping"},
        max_mutation_scope="none",
        requires_sandbox=False,
        description="Produces plans, schemas, and POEs. Zero raw code mutation.",
    ),
    EngineeringRole.BUILDER: RoleContract(
        role=EngineeringRole.BUILDER,
        required_capabilities={"code_synthesis", "tool_calling"},
        max_mutation_scope="scoped_files",
        requires_sandbox=True,
        description="Writes implementations in disposable or target worktrees.",
    ),
    EngineeringRole.CRITIC: RoleContract(
        role=EngineeringRole.CRITIC,
        required_capabilities={"ast_parsing", "pattern_matching"},
        max_mutation_scope="none",
        requires_sandbox=False,
        description="Evaluates code without executing or mutating.",
    ),
    EngineeringRole.TESTER: RoleContract(
        role=EngineeringRole.TESTER,
        required_capabilities={"test_runner", "terminal_execution"},
        max_mutation_scope="none",
        requires_sandbox=True,
        description="Executes test suites and measures coverage and pass rates.",
    ),
    EngineeringRole.SECURITY: RoleContract(
        role=EngineeringRole.SECURITY,
        required_capabilities={"regex_scanning", "entropy_analysis"},
        max_mutation_scope="none",
        requires_sandbox=False,
        description="Scans for hardcoded secrets, permission leaks, and path contamination.",
    ),
    EngineeringRole.REVIEWER: RoleContract(
        role=EngineeringRole.REVIEWER,
        required_capabilities={"diff_analysis"},
        max_mutation_scope="none",
        requires_sandbox=False,
        description="Verifies git diff cleanliness and commit messages.",
    ),
    EngineeringRole.REPAIR: RoleContract(
        role=EngineeringRole.REPAIR,
        required_capabilities={"stack_trace_analysis", "surgical_patching"},
        max_mutation_scope="scoped_files",
        requires_sandbox=True,
        description="Narrowest durable fixes for failing test suites.",
    ),
    EngineeringRole.ARBITER: RoleContract(
        role=EngineeringRole.ARBITER,
        required_capabilities={"consensus_eval", "evidence_audit"},
        max_mutation_scope="full_workspace",
        requires_sandbox=False,
        requires_human_gate=True,
        description="Evaluates touchdown evidence tuples and grants merge/commit approval.",
    ),
}
