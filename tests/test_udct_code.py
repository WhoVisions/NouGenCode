"""
Unit and Property Tests for NouGenCode UDCT Engine.
==================================================
Verifies:
1. Determinism: G(I_1) == G(I_2) given identical specs.
2. Architecture Derivation: Rules calculate layers, routes, and modules.
3. Dependency Formula: D = f(F, R, A, DB, T).
4. Test Obligation Formula: N_tests = N_public + N_errors + N_boundaries.
5. Multi-language Rendering: TypeScript & Python service templates.
"""

import pytest
from nougencode.udct_code import (
    CodeCalculationEngine,
    DeterministicCodeRenderer,
    FrameworkType,
    NormalizedSpec,
    ProjectType,
    TargetLanguage,
)


def test_udct_code_determinism_invariant():
    """G(I_1) == G(I_2): Same spec produces identical hash and exact IR structure."""
    spec1 = NormalizedSpec(
        project_name="OutpostAuth",
        project_type=ProjectType.WEB_APP,
        framework=FrameworkType.NEXTJS,
        language=TargetLanguage.TYPESCRIPT,
        router="app",
        database="postgres",
        orm="prisma",
        auth="oauth",
        entities=["User", "Session"],
        capabilities=["create", "read", "delete"],
    )
    spec2 = NormalizedSpec(
        project_name="OutpostAuth",
        project_type=ProjectType.WEB_APP,
        framework=FrameworkType.NEXTJS,
        language=TargetLanguage.TYPESCRIPT,
        router="app",
        database="postgres",
        orm="prisma",
        auth="oauth",
        entities=["User", "Session"],
        capabilities=["create", "read", "delete"],
    )

    ir1 = CodeCalculationEngine.solve_project_ir(spec1)
    ir2 = CodeCalculationEngine.solve_project_ir(spec2)

    assert ir1.spec_hash == ir2.spec_hash
    assert ir1.to_dict() == ir2.to_dict()


def test_udct_code_dependency_and_architecture_derivation():
    """Rules calculate Next.js app router + OAuth + Prisma files and dependencies."""
    spec = NormalizedSpec(
        project_name="NextApp",
        project_type=ProjectType.WEB_APP,
        framework=FrameworkType.NEXTJS,
        language=TargetLanguage.TYPESCRIPT,
        router="app",
        orm="prisma",
        auth="oauth",
        test_runner="vitest",
        e2e_runner="playwright",
        entities=["Account"],
    )
    ir = CodeCalculationEngine.solve_project_ir(spec)

    # Required Next.js + OAuth + Prisma dependencies
    assert "next" in ir.dependencies
    assert "next-auth" in ir.dependencies
    assert "@prisma/client" in ir.dependencies
    assert "prisma" in ir.dev_dependencies
    assert "vitest" in ir.dev_dependencies
    assert "playwright" in ir.dev_dependencies

    # Derived file paths
    paths = [m.path for m in ir.modules]
    assert "app/api/auth/[...nextauth]/route.ts" in paths
    assert "middleware.ts" in paths
    assert "prisma/schema.prisma" in paths
    assert "lib/auth.ts" in paths
    assert "lib/db.ts" in paths
    assert "lib/services/account.service.ts" in paths


def test_udct_test_coverage_formula():
    """N_tests = N_public_methods + N_failure_branches + N_boundary_conditions.
    For 1 entity with 3 capabilities ('create', 'read', 'delete'):
    Methods = ['create_account', 'get_account', 'list_accounts', 'delete_account'] (4 methods).
    Each method has 1 nominal + 1 error branch + 1 boundary condition => 3 * 4 = 12 tests.
    """
    spec = NormalizedSpec(
        project_name="BankingService",
        project_type=ProjectType.API_SERVICE,
        framework=FrameworkType.FASTAPI,
        language=TargetLanguage.PYTHON,
        entities=["Account"],
        capabilities=["create", "read", "delete"],
    )
    ir = CodeCalculationEngine.solve_project_ir(spec)

    # 4 methods: create_account, get_account, list_accounts, delete_account
    assert len(ir.functions) == 4
    # Each function obligates 3 tests: unit, failure, boundary
    assert ir.total_test_obligations_count == 12

    types = [t.test_type for t in ir.test_obligations]
    assert types.count("unit") == 4
    assert types.count("failure") == 4
    assert types.count("boundary") == 4


def test_udct_code_renderer_typescript_and_python():
    """Deterministic Code Renderer produces valid class representations."""
    spec = NormalizedSpec(
        project_name="Polyglot",
        project_type=ProjectType.API_SERVICE,
        framework=FrameworkType.FASTAPI,
        language=TargetLanguage.PYTHON,
        entities=["User"],
        capabilities=["create", "read"],
    )
    ir = CodeCalculationEngine.solve_project_ir(spec)

    ts_code = DeterministicCodeRenderer.render_service_file("User", ir.functions, TargetLanguage.TYPESCRIPT)
    py_code = DeterministicCodeRenderer.render_service_file("User", ir.functions, TargetLanguage.PYTHON)
    rust_code = DeterministicCodeRenderer.render_service_file("User", ir.functions, TargetLanguage.RUST)
    go_code = DeterministicCodeRenderer.render_service_file("User", ir.functions, TargetLanguage.GO)
    cpp_code = DeterministicCodeRenderer.render_service_file("User", ir.functions, TargetLanguage.CPP)
    cs_code = DeterministicCodeRenderer.render_service_file("User", ir.functions, TargetLanguage.CSHARP)
    kt_code = DeterministicCodeRenderer.render_service_file("User", ir.functions, TargetLanguage.KOTLIN)

    assert "export class UserService" in ts_code
    assert "async create_user(" in ts_code
    assert "class UserService:" in py_code
    assert "async def create_user(" in py_code

    # Multi-language verification: Rust & Go
    assert "pub struct UserService;" in rust_code
    assert "pub async fn create_user(&self" in rust_code
    assert "type UserService struct{}" in go_code
    assert "func (s *UserService) CreateUser(ctx context.Context" in go_code

    # Polyglot verification: C++, C#, Kotlin
    assert "class UserService {" in cpp_code
    assert "virtual UserData create_user(" in cpp_code
    assert "public class UserService" in cs_code
    assert "public async Task<UserData> CreateUserAsync(" in cs_code
    assert "class UserService {" in kt_code
    assert "suspend fun createUser(" in kt_code

    manifest = DeterministicCodeRenderer.render_manifest(ir)
    assert "Universal Deterministic Architecture Manifest" in manifest
    assert "**Calculated Test Obligations**: 9" in manifest


def test_udct_polyglot_spec_resolutions():
    """Verify C++, C#, and Kotlin specs derive correct extensions and dependencies."""
    spec_cpp = NormalizedSpec(
        project_name="NativeAudioEngine",
        project_type=ProjectType.LIBRARY,
        framework=FrameworkType.NONE,
        language=TargetLanguage.CPP,
        entities=["Mixer"],
    )
    ir_cpp = CodeCalculationEngine.solve_project_ir(spec_cpp)
    assert "Qt6::Core" in ir_cpp.dependencies
    assert any(m.path.endswith(".cpp") for m in ir_cpp.modules)

    spec_cs = NormalizedSpec(
        project_name="WaveBridge",
        project_type=ProjectType.API_SERVICE,
        framework=FrameworkType.NONE,
        language=TargetLanguage.CSHARP,
        entities=["Plugin"],
    )
    ir_cs = CodeCalculationEngine.solve_project_ir(spec_cs)
    assert "Microsoft.Extensions.DependencyInjection" in ir_cs.dependencies
    assert any(m.path.endswith(".cs") for m in ir_cs.modules)

    spec_kt = NormalizedSpec(
        project_name="AndroidCompanion",
        project_type=ProjectType.WEB_APP,
        framework=FrameworkType.NONE,
        language=TargetLanguage.KOTLIN,
        entities=["Profile"],
    )
    ir_kt = CodeCalculationEngine.solve_project_ir(spec_kt)
    assert "org.jetbrains.kotlinx:kotlinx-coroutines-core" in ir_kt.dependencies
    assert any(m.path.endswith(".kt") for m in ir_kt.modules)
