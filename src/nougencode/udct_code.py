"""
NouGenCode Universal Deterministic Code Templates (UDCT) Engine.
================================================================

Architecture Specification:
    Codebase = Render(Solve(Normalize(Intent), Environment, Constraints, Invariants))

The 5-Layer Compilation Pipeline:
    1. SPEC (Structured Intent: project_type, framework, router, db, auth, etc.)
    2. NORMALIZATION (Canonical lowercasing, alias expansion, default injection)
    3. CALCULATION ENGINE (Deterministic math/logic derivations: files, layers, dependencies, routes)
    4. INTERMEDIATE REPRESENTATION (Language-neutral ProjectIR)
    5. CODE TEMPLATES (Renderers for TypeScript, Python, Rust, Go)
    6. VALIDATION (Test obligation counts N_tests = N_methods + N_errors + N_boundaries)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


class ProjectType(str, Enum):
    WEB_APP = "web_app"
    API_SERVICE = "api_service"
    CLI_TOOL = "cli_tool"
    LIBRARY = "library"
    WORKER = "worker"


class FrameworkType(str, Enum):
    NEXTJS = "nextjs"
    FASTAPI = "fastapi"
    EXPRESS = "express"
    ACTIX = "actix"
    GIN = "gin"
    NONE = "none"


class TargetLanguage(str, Enum):
    TYPESCRIPT = "typescript"
    PYTHON = "python"
    RUST = "rust"
    GO = "go"
    CPP = "cpp"
    CSHARP = "csharp"
    KOTLIN = "kotlin"


@dataclass
class NormalizedSpec:
    """Normalized structured intent."""
    project_name: str
    project_type: ProjectType
    framework: FrameworkType
    language: TargetLanguage
    router: str = "app"
    database: Optional[str] = "postgres"
    orm: Optional[str] = "prisma"
    auth: Optional[str] = "oauth"
    auth_providers: List[str] = field(default_factory=lambda: ["google", "github"])
    entities: List[str] = field(default_factory=lambda: ["User"])
    capabilities: List[str] = field(default_factory=lambda: ["create", "read", "update", "delete"])
    test_runner: str = "vitest"
    e2e_runner: Optional[str] = "playwright"
    deployment: str = "cloudflare"
    extra_features: Dict[str, bool] = field(default_factory=dict)

    def canonical_hash(self) -> str:
        s = f"{self.project_name}:{self.project_type.value}:{self.framework.value}:{self.language.value}:{self.router}:{self.database}:{self.orm}:{self.auth}:{sorted(self.entities)}:{sorted(self.capabilities)}"
        return hashlib.sha256(s.encode("utf-8")).hexdigest()


@dataclass
class IRModule:
    path: str
    purpose: str
    layer: str
    exports: List[str] = field(default_factory=list)
    imports: Dict[str, str] = field(default_factory=dict)


@dataclass
class IRInterface:
    name: str
    module_path: str
    fields: Dict[str, str] = field(default_factory=dict)


@dataclass
class IRFunction:
    name: str
    module_path: str
    params: Dict[str, str] = field(default_factory=dict)
    return_type: str = "void"
    is_async: bool = True
    error_branches_count: int = 1
    boundary_conditions_count: int = 1


@dataclass
class IRTestObligation:
    target_module: str
    target_function: str
    test_type: str  # "unit", "failure", "boundary"
    test_name: str
    description: str


@dataclass
class ProjectIR:
    """Language-neutral Project Intermediate Representation."""
    spec_hash: str
    project_name: str
    language: TargetLanguage
    modules: List[IRModule] = field(default_factory=list)
    interfaces: List[IRInterface] = field(default_factory=list)
    functions: List[IRFunction] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    dev_dependencies: List[str] = field(default_factory=list)
    routes: List[str] = field(default_factory=list)
    schemas: List[str] = field(default_factory=list)
    test_obligations: List[IRTestObligation] = field(default_factory=list)
    invariants: List[str] = field(default_factory=list)

    @property
    def total_test_obligations_count(self) -> int:
        return len(self.test_obligations)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spec_hash": self.spec_hash,
            "project_name": self.project_name,
            "language": self.language.value,
            "modules": [asdict(m) for m in self.modules],
            "interfaces": [asdict(i) for i in self.interfaces],
            "functions": [asdict(f) for f in self.functions],
            "dependencies": self.dependencies,
            "dev_dependencies": self.dev_dependencies,
            "routes": self.routes,
            "schemas": self.schemas,
            "test_obligations_count": self.total_test_obligations_count,
            "test_obligations": [asdict(t) for t in self.test_obligations],
            "invariants": self.invariants,
        }


class CodeCalculationEngine:
    """Deterministic Calculation Engine.
    Derives file trees, dependencies, routes, and test counts via strict equations.
    """

    @classmethod
    def calculate_dependencies(cls, spec: NormalizedSpec) -> Tuple[List[str], List[str]]:
        """D = f(Framework, Router, Auth, Database, Testing)."""
        deps: Set[str] = set()
        dev_deps: Set[str] = set()

        if spec.language == TargetLanguage.TYPESCRIPT:
            dev_deps.add("typescript")
            if spec.framework == FrameworkType.NEXTJS:
                deps.update(["next", "react", "react-dom"])
                if spec.auth == "oauth":
                    deps.add("next-auth")
                if spec.orm == "prisma":
                    deps.add("@prisma/client")
                    dev_deps.add("prisma")
                if spec.test_runner == "vitest":
                    dev_deps.add("vitest")
                if spec.e2e_runner == "playwright":
                    dev_deps.add("playwright")
            elif spec.framework == FrameworkType.EXPRESS:
                deps.update(["express", "cors", "dotenv"])
                dev_deps.update(["@types/express", "@types/node", "ts-node-dev"])

        elif spec.language == TargetLanguage.PYTHON:
            if spec.framework == FrameworkType.FASTAPI:
                deps.update(["fastapi", "uvicorn", "pydantic"])
                if spec.database:
                    deps.add("sqlalchemy")
                dev_deps.update(["pytest", "pytest-asyncio", "httpx", "ruff"])

        elif spec.language == TargetLanguage.RUST:
            deps.update(["tokio", "serde", "serde_json"])
            dev_deps.update(["tokio-test"])

        elif spec.language == TargetLanguage.GO:
            deps.update(["github.com/google/uuid"])
            dev_deps.update(["github.com/stretchr/testify"])

        elif spec.language == TargetLanguage.CPP:
            deps.update(["Qt6::Core", "Qt6::Network"])
            dev_deps.update(["Catch2", "cmake"])

        elif spec.language == TargetLanguage.CSHARP:
            deps.update(["Microsoft.Extensions.DependencyInjection", "Microsoft.Extensions.Logging"])
            dev_deps.update(["xunit", "xunit.runner.visualstudio"])

        elif spec.language == TargetLanguage.KOTLIN:
            deps.update(["org.jetbrains.kotlinx:kotlinx-coroutines-core", "org.jetbrains.kotlinx:kotlinx-serialization-json"])
            dev_deps.update(["org.jetbrains.kotlin:kotlin-test", "org.jetbrains.kotlinx:kotlinx-coroutines-test"])

        return sorted(list(deps)), sorted(list(dev_deps))

    @classmethod
    def calculate_entity_methods(cls, entity: str, capabilities: Sequence[str]) -> List[str]:
        """Deterministic method list derivation."""
        e = entity.lower().strip()
        methods = []
        if "create" in capabilities:
            methods.append(f"create_{e}")
        if "read" in capabilities:
            methods.append(f"get_{e}")
            methods.append(f"list_{e}s")
        if "update" in capabilities:
            methods.append(f"update_{e}")
        if "delete" in capabilities:
            methods.append(f"delete_{e}")
        return methods

    @classmethod
    def calculate_test_coverage_formula(
        cls,
        num_public_methods: int,
        num_error_branches: int,
        num_boundary_conditions: int,
    ) -> int:
        """N_tests = N_public_methods + N_failure_branches + N_boundary_conditions."""
        return num_public_methods + num_error_branches + num_boundary_conditions

    @classmethod
    def solve_project_ir(cls, spec: NormalizedSpec) -> ProjectIR:
        """Converts NormalizedSpec into fully populated deterministic ProjectIR."""
        deps, dev_deps = cls.calculate_dependencies(spec)
        modules: List[IRModule] = []
        interfaces: List[IRInterface] = []
        functions: List[IRFunction] = []
        routes: List[str] = []
        schemas: List[str] = []
        test_obligations: List[IRTestObligation] = []
        invariants: List[str] = []

        ext_map = {
            TargetLanguage.TYPESCRIPT: "ts",
            TargetLanguage.PYTHON: "py",
            TargetLanguage.RUST: "rs",
            TargetLanguage.GO: "go",
            TargetLanguage.CPP: "cpp",
            TargetLanguage.CSHARP: "cs",
            TargetLanguage.KOTLIN: "kt",
        }
        ext = ext_map.get(spec.language, "ts")

        # Next.js App router specific derivations
        if spec.framework == FrameworkType.NEXTJS and spec.router == "app":
            routes.append("app/page.tsx")
            routes.append("app/layout.tsx")
            modules.append(IRModule(path="app/page.tsx", purpose="Root Page", layer="presentation"))
            modules.append(IRModule(path="app/layout.tsx", purpose="Root Layout", layer="presentation"))

            if spec.auth == "oauth":
                routes.append("app/api/auth/[...nextauth]/route.ts")
                modules.append(IRModule(path="app/api/auth/[...nextauth]/route.ts", purpose="OAuth Endpoint", layer="api"))
                modules.append(IRModule(path="lib/auth.ts", purpose="Auth Options & Session Provider", layer="auth"))
                modules.append(IRModule(path="middleware.ts", purpose="Route Edge Protection", layer="security"))
                invariants.append("Protected routes must reject unauthenticated requests with 401.")

            if spec.orm == "prisma":
                modules.append(IRModule(path="prisma/schema.prisma", purpose="Database Schema", layer="persistence"))
                modules.append(IRModule(path="lib/db.ts", purpose="Global Prisma Client Instance", layer="persistence"))
                invariants.append("Prisma client singleton pattern must prevent multiple instances in development.")

        # Entity modules and test obligations
        for ent in spec.entities:
            ent_clean = ent.strip()
            ent_lower = ent_clean.lower()

            model_path = f"src/models/{ent_lower}.model.{ext}" if not (spec.framework == FrameworkType.NEXTJS) else f"lib/models/{ent_lower}.{ext}"
            repo_path = f"src/repositories/{ent_lower}.repository.{ext}" if not (spec.framework == FrameworkType.NEXTJS) else f"lib/repositories/{ent_lower}.repository.{ext}"
            service_path = f"src/services/{ent_lower}.service.{ext}" if not (spec.framework == FrameworkType.NEXTJS) else f"lib/services/{ent_lower}.service.{ext}"
            test_path = f"tests/{ent_lower}.service.test.{ext}"

            modules.append(IRModule(path=model_path, purpose=f"{ent_clean} Model Definition", layer="model"))
            modules.append(IRModule(path=repo_path, purpose=f"{ent_clean} Persistence Repository", layer="repository"))
            modules.append(IRModule(path=service_path, purpose=f"{ent_clean} Business Logic Service", layer="service"))
            modules.append(IRModule(path=test_path, purpose=f"{ent_clean} Service Test Ladder", layer="test"))

            schemas.append(f"{ent_clean}Schema")
            interfaces.append(IRInterface(name=f"{ent_clean}Data", module_path=model_path, fields={"id": "string", "createdAt": "Date"}))

            # Calculate methods and tests for this entity service
            methods = cls.calculate_entity_methods(ent_clean, spec.capabilities)
            for m in methods:
                # 1 public method + 1 error branch + 1 boundary condition
                fn = IRFunction(
                    name=m,
                    module_path=service_path,
                    params={"id": "string"} if "get" in m or "update" in m or "delete" in m else {"data": f"{ent_clean}Data"},
                    return_type=f"{ent_clean}Data" if "delete" not in m else "boolean",
                    error_branches_count=1,
                    boundary_conditions_count=1,
                )
                functions.append(fn)

                # N_tests formula: 1 nominal + 1 failure + 1 boundary
                test_obligations.append(IRTestObligation(
                    target_module=service_path,
                    target_function=m,
                    test_type="unit",
                    test_name=f"test_{m}_success",
                    description=f"Nominal success path for {m}",
                ))
                test_obligations.append(IRTestObligation(
                    target_module=service_path,
                    target_function=m,
                    test_type="failure",
                    test_name=f"test_{m}_handles_error",
                    description=f"Error propagation and failure branch for {m}",
                ))
                test_obligations.append(IRTestObligation(
                    target_module=service_path,
                    target_function=m,
                    test_type="boundary",
                    test_name=f"test_{m}_boundary_condition",
                    description=f"Boundary condition and edge case for {m}",
                ))

        invariants.append(f"Total test obligations must equal N_public ({len(functions)}) + N_errors ({sum(f.error_branches_count for f in functions)}) + N_boundaries ({sum(f.boundary_conditions_count for f in functions)}) = {len(test_obligations)}.")

        return ProjectIR(
            spec_hash=spec.canonical_hash(),
            project_name=spec.project_name,
            language=spec.language,
            modules=modules,
            interfaces=interfaces,
            functions=functions,
            dependencies=deps,
            dev_dependencies=dev_deps,
            routes=routes,
            schemas=schemas,
            test_obligations=test_obligations,
            invariants=invariants,
        )


class DeterministicCodeRenderer:
    """Universal Template Renderer for ProjectIR."""

    @classmethod
    def render_manifest(cls, ir: ProjectIR) -> str:
        """Renders architecture manifest and file tree."""
        lines = [
            f"# 🏗️ Universal Deterministic Architecture Manifest — {ir.project_name}",
            f"**Spec Hash**: `{ir.spec_hash}`",
            f"**Language**: `{ir.language.value}`",
            f"**Calculated Test Obligations**: {ir.total_test_obligations_count}",
            "",
            "## 📦 Calculated Dependencies",
            "```json",
            json.dumps({"dependencies": ir.dependencies, "devDependencies": ir.dev_dependencies}, indent=2),
            "```",
            "",
            "## 📁 Derived File Tree",
        ]
        for m in ir.modules:
            lines.append(f"- `{m.path}` ({m.layer}): {m.purpose}")
        
        lines.append("")
        lines.append("## 🧪 Test Obligations Ladder")
        for t in ir.test_obligations:
            lines.append(f"- `[{t.test_type.upper()}]` {t.test_name} ➔ `{t.target_function}` ({t.description})")

        lines.append("")
        lines.append("## 🛡️ Invariants")
        for inv in ir.invariants:
            lines.append(f"- {inv}")

        return "\n".join(lines)

    @classmethod
    def render_service_file(cls, entity: str, functions: Sequence[IRFunction], language: TargetLanguage) -> str:
        """Renders clean service class from calculated IR functions."""
        e_title = entity.title()
        if language == TargetLanguage.TYPESCRIPT:
            code = [f"// Deterministically generated service for {e_title}", f"export class {e_title}Service {{"]
            for fn in functions:
                param_str = ", ".join(f"{p}: {t}" for p, t in fn.params.items())
                code.append(f"  async {fn.name}({param_str}): Promise<{fn.return_type}> {{")
                code.append(f"    // Calculated error branches: {fn.error_branches_count}, boundaries: {fn.boundary_conditions_count}")
                code.append(f"    if (!{list(fn.params.keys())[0] if fn.params else 'true'}) throw new Error('Invalid input');")
                code.append(f"    return null as any;")
                code.append("  }\n")
            code.append("}")
            return "\n".join(code)

        elif language == TargetLanguage.PYTHON:
            code = [f"# Deterministically generated service for {e_title}", f"class {e_title}Service:"]
            for fn in functions:
                param_str = ", ".join(f"{p}: {t}" for p, t in fn.params.items())
                code.append(f"    async def {fn.name}(self, {param_str}) -> {fn.return_type}:")
                code.append(f"        # Calculated error branches: {fn.error_branches_count}, boundaries: {fn.boundary_conditions_count}")
                code.append("        pass\n")
            return "\n".join(code)

        elif language == TargetLanguage.RUST:
            code = [
                f"// Deterministically generated service for {e_title}",
                f"pub struct {e_title}Service;",
                "",
                f"impl {e_title}Service {{",
            ]
            for fn in functions:
                param_parts = [f"{p}: &str" for p in fn.params.keys()]
                param_str = ", ".join(["&self"] + param_parts)
                ret_type = "Result<bool, Box<dyn std::error::Error>>" if fn.return_type == "boolean" else f"Result<{e_title}Data, Box<dyn std::error::Error>>"
                code.append(f"    pub async fn {fn.name}({param_str}) -> {ret_type} {{")
                code.append(f"        // Calculated error branches: {fn.error_branches_count}, boundaries: {fn.boundary_conditions_count}")
                if fn.return_type == "boolean":
                    code.append("        Ok(true)")
                else:
                    code.append(f"        Ok({e_title}Data::default())")
                code.append("    }\n")
            code.append("}")
            return "\n".join(code)

        elif language == TargetLanguage.GO:
            code = [
                f"// Deterministically generated service for {e_title}",
                "package service",
                "",
                "import \"context\"",
                "",
                f"type {e_title}Service struct{{}}",
                "",
                f"func New{e_title}Service() *{e_title}Service {{",
                f"    return &{e_title}Service{{}}",
                "}",
            ]
            for fn in functions:
                # Convert snake_case to PascalCase for exported Go methods
                go_method = "".join(part.title() for part in fn.name.split("_"))
                param_parts = [f"{p} string" for p in fn.params.keys()]
                param_str = ", ".join(["ctx context.Context"] + param_parts)
                ret_type = "(bool, error)" if fn.return_type == "boolean" else f"(*{e_title}Data, error)"
                code.append(f"\nfunc (s *{e_title}Service) {go_method}({param_str}) {ret_type} {{")
                code.append(f"    // Calculated error branches: {fn.error_branches_count}, boundaries: {fn.boundary_conditions_count}")
                if fn.return_type == "boolean":
                    code.append("    return true, nil")
                else:
                    code.append(f"    return &{e_title}Data{{}}, nil")
                code.append("}")
            return "\n".join(code)

        elif language == TargetLanguage.CPP:
            code = [
                f"// Deterministically generated service for {e_title}",
                "#pragma once",
                "",
                "#include <memory>",
                "#include <string>",
                "#include <optional>",
                "",
                f"class {e_title}Service {{",
                "public:",
                f"    {e_title}Service() = default;",
                f"    virtual ~{e_title}Service() = default;",
            ]
            for fn in functions:
                param_parts = [f"const std::string& {p}" for p in fn.params.keys()]
                param_str = ", ".join(param_parts)
                ret_type = "bool" if fn.return_type == "boolean" else f"{e_title}Data"
                code.append(f"\n    virtual {ret_type} {fn.name}({param_str}) {{")
                code.append(f"        // Calculated error branches: {fn.error_branches_count}, boundaries: {fn.boundary_conditions_count}")
                if fn.return_type == "boolean":
                    code.append("        return true;")
                else:
                    code.append(f"        return {e_title}Data{{}};")
                code.append("    }")
            code.append("};")
            return "\n".join(code)

        elif language == TargetLanguage.CSHARP:
            code = [
                f"// Deterministically generated service for {e_title}",
                "using System;",
                "using System.Threading;",
                "using System.Threading.Tasks;",
                "",
                "namespace Services",
                "{",
                f"    public class {e_title}Service",
                "    {",
                f"        public {e_title}Service() {{ }}",
            ]
            for fn in functions:
                cs_method = "".join(part.title() for part in fn.name.split("_"))
                param_parts = [f"string {p}" for p in fn.params.keys()]
                param_str = ", ".join(param_parts + ["CancellationToken ct = default"])
                ret_type = "Task<bool>" if fn.return_type == "boolean" else f"Task<{e_title}Data>"
                code.append(f"\n        public async {ret_type} {cs_method}Async({param_str})")
                code.append("        {")
                code.append(f"            // Calculated error branches: {fn.error_branches_count}, boundaries: {fn.boundary_conditions_count}")
                code.append("            await Task.Yield();")
                if fn.return_type == "boolean":
                    code.append("            return true;")
                else:
                    code.append(f"            return new {e_title}Data();")
                code.append("        }")
            code.append("    }")
            code.append("}")
            return "\n".join(code)

        elif language == TargetLanguage.KOTLIN:
            code = [
                f"// Deterministically generated service for {e_title}",
                "package com.nougen.services",
                "",
                "import kotlinx.coroutines.Dispatchers",
                "import kotlinx.coroutines.withContext",
                "",
                f"class {e_title}Service {{",
            ]
            for fn in functions:
                parts = fn.name.split("_")
                kt_method = parts[0] + "".join(p.title() for p in parts[1:])
                param_parts = [f"{p}: String" for p in fn.params.keys()]
                param_str = ", ".join(param_parts)
                ret_type = "Boolean" if fn.return_type == "boolean" else f"{e_title}Data"
                code.append(f"\n    suspend fun {kt_method}({param_str}): {ret_type} = withContext(Dispatchers.IO) {{")
                code.append(f"        // Calculated error branches: {fn.error_branches_count}, boundaries: {fn.boundary_conditions_count}")
                if fn.return_type == "boolean":
                    code.append("        true")
                else:
                    code.append(f"        {e_title}Data()")
                code.append("    }")
            code.append("}")
            return "\n".join(code)

        return "// Language renderer not implemented"
