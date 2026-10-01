"""Command-line interface for NouGenCode."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .models import ScanSummary
from .scanners.ast_scanner import AstDeadCodeScanner
from .scanners.orphan_scanner import OrphanFileScanner
from .scanners.dep_scanner import DependencyScanner
from .reporters.console import ConsoleReporter
from .shard_recorder import ShardRecorder


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="nougencode",
        description="NouGenCode: Universal Dynamic Deterministic Software Engineering Control Plane.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Optional subcommand")

    # discover subcommand (Waterflow)
    p_disc = subparsers.add_parser("discover", help="Discover local hardware, runtimes, and provider capabilities")
    p_disc.add_argument("--json", action="store_true", help="Output hardware and providers as JSON")

    # audit subcommand (Concentric Security Gate)
    p_audit = subparsers.add_parser("audit", help="Audit repository or file for security invariants, paths, and secrets")
    p_audit.add_argument("audit_target", nargs="?", default=".", help="Target file or directory to audit")

    # route subcommand (Empirical posterior preview)
    p_route = subparsers.add_parser("route", help="Empirically preview optimal provider resolution for a role")
    p_route.add_argument("--role", default="builder", help="Role to evaluate (architect, builder, critic, tester, security)")

    p_profile = subparsers.add_parser("capability-profile", help="Validate and resolve a scheduler capability profile")
    profile_subparsers = p_profile.add_subparsers(dest="profile_command", required=True)
    p_profile_validate = profile_subparsers.add_parser("validate", help="Validate profile evidence and print its current scheduler view")
    p_profile_validate.add_argument("profile_path", type=Path, help="Path to a JSON capability profile")
    p_profile_validate.add_argument("--as-of", help="Timezone-qualified ISO timestamp for deterministic freshness evaluation")

    p_golden = subparsers.add_parser("golden-slice", help="Assess a provenance-carrying evidence request and print a proof envelope")
    p_golden.add_argument("request_path", type=Path, help="Path to a golden-slice request JSON file")

    p_fabric = subparsers.add_parser("change-fabric", help="Validate change contract and execute trustworthy change fabric")
    p_fabric.add_argument("--session-id", default="session-cli", help="Session ID")
    p_fabric.add_argument("--contract-id", default="CC-CLI-001", help="Contract ID")
    p_fabric.add_argument("--files", nargs="*", default=[], help="Modified files")
    p_fabric.add_argument("--lines", type=int, default=0, help="Lines changed")
    p_fabric.add_argument("--json", action="store_true", help="Output summary as JSON")

    # Default scan flags
    parser.add_argument("path", nargs="?", default=".", help="Target directory or file to scan (default: current directory)")
    parser.add_argument("-i", "--interactive", action="store_true", help="Launch interactive autonomous terminal session")
    parser.add_argument("--save-shard", action="store_true", help="Record scan receipt into NouGen shards")
    parser.add_argument("--no-ast", action="store_true", help="Skip AST deadcode scanner")
    parser.add_argument("--no-orphans", action="store_true", help="Skip orphan root script scanner")
    parser.add_argument("--no-deps", action="store_true", help="Skip dependency scanner")
    parser.add_argument("--json", action="store_true", help="Output summary as JSON")

    args = parser.parse_args()

    # Handle Subcommands
    if args.subcommand == "discover":
        from .discovery.waterflow import WaterflowDiscovery
        hw = WaterflowDiscovery.inspect_hardware()
        providers = WaterflowDiscovery.discover_providers()
        if args.json:
            import json
            print(json.dumps({
                "hardware": hw.__dict__,
                "providers": {k: v.__dict__ for k, v in providers.items()},
            }, indent=2))
        else:
            print(f"Hardware: {hw.os_name} ({hw.architecture}) | {hw.cpu_cores} cores | GPU: {hw.has_gpu} ({hw.gpu_type})")
            print("Discovered Providers:")
            for pid, cap in providers.items():
                avail = "ONLINE" if cap.is_available else "OFFLINE"
                print(f"  * {cap.name} [{avail}] — Roles: {', '.join(cap.supported_roles)} ({cap.cost_tier})")
        return 0

    if args.subcommand == "audit":
        from .security.invariants import ConcentricSecurityGate
        audit_path = Path(args.audit_target).resolve()
        violations = []
        if audit_path.is_file():
            violations.extend(ConcentricSecurityGate.audit_code(audit_path.read_text(errors="replace")))
        elif audit_path.is_dir():
            for f in audit_path.rglob("*.py"):
                if any(p in f.parts for p in (".venv", "node_modules", ".git")):
                    continue
                violations.extend(ConcentricSecurityGate.audit_code(f.read_text(errors="replace")))
        if violations:
            print(f"⚠️ Found {len(violations)} security / invariant violations:")
            for v in violations:
                print(f"  - [{v.violation_type}] {v.message} ({v.matched_snippet})")
            return 1
        print("✅ Invariant audit passed: 0 secrets, 0 personal paths, 0 security leaks.")
        return 0

    if args.subcommand == "route":
        from .roles.contracts import EngineeringRole
        from .router.empirical_router import EmpiricalProviderRouter, TaskSpecification
        from .discovery.waterflow import WaterflowDiscovery
        providers = WaterflowDiscovery.discover_providers()
        router = EmpiricalProviderRouter()
        role_enum = EngineeringRole.BUILDER
        try:
            role_enum = EngineeringRole(args.role.upper())
        except ValueError:
            pass
        task = TaskSpecification(role=role_enum)
        chosen, score = router.resolve_provider(task, providers)
        print(f"Empirical Posterior Routing for Role [{role_enum.value.upper()}]:")
        if chosen:
            print(f"  Optimal Provider: {chosen.name} (Utility: {score:.3f})")
        else:
            print("  No currently active provider declared for this role.")
        return 0

    if args.subcommand == "capability-profile":
        import json

        from .capability_profile import CapabilityProfileError, capability_summary, load_profile

        try:
            profile = load_profile(args.profile_path)
            as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else None
            print(json.dumps(capability_summary(profile, as_of=as_of), sort_keys=True))
        except (CapabilityProfileError, ValueError) as exc:
            sys.stderr.write(f"Capability profile invalid: {exc}\n")
            return 2
        return 0

    if args.subcommand == "golden-slice":
        import json

        from .core.golden_slice import run_golden_slice_request

        try:
            request = json.loads(args.request_path.read_text(encoding="utf-8"))
            result = run_golden_slice_request(request)
            print(json.dumps(result.to_dict(), sort_keys=True))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            sys.stderr.write(f"Golden-slice request invalid: {exc}\n")
            return 2
        return 0

    if args.subcommand == "change-fabric":
        import json

        from .fabric import ChangeContract, FunctionalRequirement, ReviewConstraint, ChangeFabricEngine

        contract = ChangeContract(
            contract_id=args.contract_id,
            title="CLI Change Fabric Invocation",
            functional_requirements=(
                FunctionalRequirement(
                    req_id="FR-CLI",
                    description="Autonomous change execution",
                    target_artifacts=tuple(args.files) if args.files else ("src/nougencode/cli.py",),
                    invariants=("DETERMINISTIC_PROOF",),
                    acceptance_tests=(),
                ),
            ),
            review_constraints=ReviewConstraint(
                constraint_id="RC-CLI",
                max_mutation_files=20,
                max_mutation_lines=2000,
                required_reviewers=("Apollo",),
                forbidden_patterns=(),
            ),
        )

        engine = ChangeFabricEngine()
        result = engine.execute_change_cycle(
            session_id=args.session_id,
            contract=contract,
            modified_files=args.files,
            lines_changed=args.lines,
        )

        if args.json:
            print(json.dumps({
                "status": result.status,
                "session_id": result.session_id,
                "contract_id": result.contract_id,
                "receipt_hash": result.receipt_hash,
                "coherence_debt": result.coherence_report.coherence_debt_score,
                "route": {
                    "provider": result.route_decision.selected_provider_id,
                    "model": result.route_decision.selected_model_id,
                },
                "mutation_valid": result.mutation_valid,
            }, indent=2))
        else:
            print(f"Change Fabric Execution: [{result.status}]")
            print(f"  Receipt Hash: {result.receipt_hash}")
            print(f"  Coherence Debt: {result.coherence_report.coherence_debt_score}")
            print(f"  Route: {result.route_decision.selected_provider_id} -> {result.route_decision.selected_model_id}")
            print(f"  Mutation Valid: {result.mutation_valid}")
        return 0 if result.status == "ACCEPTED" else 1

    target_path = Path(args.path).resolve()

    if not target_path.exists():
        sys.stderr.write(f"Error: Path '{target_path}' does not exist.\n")
        return 1

    if args.interactive:
        from .repl import ReplSession
        repl = ReplSession(target_path if target_path.is_dir() else target_path.parent)
        repl.start()
        return 0

    summary = ScanSummary(
        target_root=str(target_path),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # 1. AST Scanner
    if not args.no_ast:
        ast_scanner = AstDeadCodeScanner()
        if target_path.is_file() and target_path.suffix == ".py":
            summary.files_scanned += 1
            for issue in ast_scanner.scan_file(target_path):
                summary.add_issue(issue)
        elif target_path.is_dir():
            for py_file in target_path.rglob("*.py"):
                if any(p in py_file.parts for p in (".venv", "node_modules", ".git", "__pycache__")):
                    continue
                summary.files_scanned += 1
                for issue in ast_scanner.scan_file(py_file):
                    summary.add_issue(issue)

    # 2. Orphan Scanner
    if not args.no_orphans and target_path.is_dir():
        orphan_scanner = OrphanFileScanner(target_path)
        for issue in orphan_scanner.scan_orphans():
            summary.add_issue(issue)

    # 3. Dependency Scanner
    if not args.no_deps and target_path.is_dir():
        dep_scanner = DependencyScanner(target_path)
        for issue in dep_scanner.scan_dependencies():
            summary.add_issue(issue)

    shard_id = None
    if args.save_shard:
        recorder = ShardRecorder()
        shard_id = recorder.record_scan_receipt(summary)

    if args.json:
        import json
        out = summary.to_dict()
        if shard_id:
            out["shard_id"] = shard_id
        print(json.dumps(out, indent=2))
    else:
        reporter = ConsoleReporter()
        reporter.print_summary(summary, shard_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())
