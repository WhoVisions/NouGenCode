"""AST deadcode and unused symbol detection."""

import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

from ..models import CodeIssue, IssueType


class SymbolUsageVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        # Defined symbols: symbol_name -> (line, col, type, node)
        self.definitions: Dict[str, Tuple[int, int, IssueType]] = {}
        # Names read/loaded in code
        self.used_names: Set[str] = set()
        # Imports: alias/name -> (line, col)
        self.imports: Dict[str, Tuple[int, int]] = {}
        # Ignored names
        self.ignored_names: Set[str] = {"__all__", "__version__", "__name__", "_"}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name
            self.imports[name] = (node.lineno, node.col_offset)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*":
                continue
            name = alias.asname or alias.name
            self.imports[name] = (node.lineno, node.col_offset)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Ignore dunder methods and special test methods
        if not (node.name.startswith("__") and node.name.endswith("__")):
            # Mark definition
            self.definitions[node.name] = (node.lineno, node.col_offset, IssueType.UNUSED_FUNCTION)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if not (node.name.startswith("__") and node.name.endswith("__")):
            self.definitions[node.name] = (node.lineno, node.col_offset, IssueType.UNUSED_FUNCTION)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.definitions[node.name] = (node.lineno, node.col_offset, IssueType.UNUSED_CLASS)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Keep track of attribute access if needed
        self.used_names.add(node.attr)
        self.generic_visit(node)


class AstDeadCodeScanner:
    """Scans python files for unused imports and unreferenced local functions/classes."""

    def __init__(self, check_cross_file: bool = False) -> None:
        self.check_cross_file = check_cross_file

    def scan_file(self, file_path: Path) -> List[CodeIssue]:
        issues: List[CodeIssue] = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=str(file_path))
        except (SyntaxError, UnicodeDecodeError) as e:
            return [
                CodeIssue(
                    issue_type=IssueType.STALE_PROTOTYPE,
                    file_path=str(file_path),
                    line_number=getattr(e, "lineno", 1) or 1,
                    symbol_name="syntax_error",
                    message=f"File fails syntax parsing: {e}",
                    severity="error",
                )
            ]

        visitor = SymbolUsageVisitor()
        visitor.visit(tree)

        # 1. Check Unused Imports
        for imp_name, (lineno, _) in visitor.imports.items():
            if imp_name not in visitor.used_names and imp_name not in visitor.ignored_names:
                issues.append(
                    CodeIssue(
                        issue_type=IssueType.UNUSED_IMPORT,
                        file_path=str(file_path),
                        line_number=lineno,
                        symbol_name=imp_name,
                        message=f"Import '{imp_name}' is imported but never referenced in file",
                        severity="warning",
                        suggested_action="Remove unused import",
                    )
                )

        # 2. Check Private/Internal unused functions & classes (_func or local helper)
        # Note: Top-level non-underscore functions might be exported API unless cross-file checked.
        # We flag private symbols unconditionally, and public ones with info or when not exported.
        for sym_name, (lineno, _, issue_type) in visitor.definitions.items():
            if sym_name.startswith("_") and sym_name not in visitor.used_names:
                issues.append(
                    CodeIssue(
                        issue_type=issue_type,
                        file_path=str(file_path),
                        line_number=lineno,
                        symbol_name=sym_name,
                        message=f"Private symbol '{sym_name}' is defined but never referenced locally",
                        severity="warning",
                        suggested_action="Prune dead private function/class",
                    )
                )

        return issues
