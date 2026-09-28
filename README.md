# ⚡ NouGenCode

**NouGenCode** is the NouGen fleet AST code cleaner, dead code scanner, and bloat sweeper with native 99% Context Mode guardrails and canonical 9-DB NouGenShards integration.

---

## 🔒 Branch & Security Policy
* **Protected Branch**: `main` (Direct pushes blocked; pull request review required).
* **Zero Path Leaks**: Dynamic discovery only (`~/.nougen/shards`, `~/.nougen/context`). No hardcoded paths.


## 🎯 Purpose & Scope

1. **AST Dead Code & Unused Symbol Detection**:
   * Scans Python source code using standard AST to detect unreferenced local imports (`UNUSED_IMPORT`).
   * Detects dead private/internal helper functions and classes (`UNUSED_FUNCTION`, `UNUSED_CLASS`).
2. **Orphan Root Script Sweeper**:
   * Identifies unreferenced scratch, temp, and ad-hoc prototype scripts (`ORPHAN_FILE`) across repository roots.
3. **Dependency & Bloat Audit**:
   * Cross-references declared dependencies in `requirements.txt` against active imports (`UNUSED_DEPENDENCY`).
4. **Shard Audit Logging**:
   * Exports scan telemetry directly into NouGen FTS5 Shard memory (`--save-shard`).

---

## 🚀 Usage

### 1. Basic Scan
```bash
# Scan current repository
nougencode

# Scan specific path or file
nougencode ./path/to/project
nougencode ./scripts/worker.py
```

### 2. Output as JSON
```bash
nougencode --json
```

### 3. Record Audit Receipt into NouGen Shards
```bash
nougencode --save-shard
```

### 4. Selective Toggles
```bash
nougencode --no-deps      # Skip requirements.txt scanning
nougencode --no-orphans   # Skip root scratch script checking
nougencode --no-ast       # Skip AST deadcode scanner
```
