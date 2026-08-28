# jakarta-impact-server — Implementation Plan

## Top-Level Overview

Build `tools/jakarta-impact/jakarta_impact_server.py` — the **Phase 1 (Impact Analysis)** FastMCP
server in the EE-volution pipeline.

The server exposes exactly **two tools**, mirroring the Layer A / Layer B split:

| Tool | Layer A role | Needs WAR? |
|---|---|---|
| `analyze_impact` | Runs Eclipse Transformer against a pre-built WAR; cross-references its output against the Discovery report to mark each file as `mechanically_rewritten`, `partially_rewritten`, or `not_rewritten` | Yes (+ JDK 11+) |
| `find_judgment_call_candidates` | Pattern-matches source files for constructs no rewrite tool can resolve automatically (reflection, dynamic proxies, SPI registrations, custom serialisation) | No |

**What this server does NOT produce:**
- Risk tiers (Low / Medium / High) — those are Layer B (the agent's) job.
- Recommendations — pure facts only.
- Any judgement about EE9→EE10 *behavioural* changes or third-party JARs bundled inside the WAR —
  both are explicitly declared out-of-scope in the output.

**Conventions inherited from `jakarta-discovery`:**
- `FastMCP` server pattern: `mcp = FastMCP(...)`, `@mcp.tool()`, `mcp.run()`
- `_iter_files` / `EXCLUDED_DIR_NAMES` shared helpers (copy-carried, not imported cross-package)
- Error shape: `{"error": "<message>"}` dict on bad inputs
- All file-read failures go into a top-level `"skipped"` list — never crash the tool
- Python 3.11+, `fastmcp>=2.14.1`

---

## Sub-Task 1 — Directory scaffold and pyproject dependency

**Intent**
Create the `tools/jakarta-impact/` directory with the server stub and declare the one new
dependency (`eclipse-transformer`) in the workspace `pyproject.toml`.

**Expected Outcomes**
- `tools/jakarta-impact/jakarta_impact_server.py` exists with the FastMCP stub (`mcp = FastMCP(...)`,
  `if __name__ == "__main__": mcp.run()`), all imports, shared helpers copied from discovery, and
  the two `@mcp.tool()` stubs returning `{"status": "not_implemented"}`.
- `tools/jakarta-impact/README.md` exists as a placeholder (will be filled in Sub-Task 4).
- `pyproject.toml` updated with `"eclipse-transformer"` (the PyPI wrapper that ships the JAR and
  exposes a `transform` CLI entry-point) — see note below.

**Eclipse Transformer dependency note:**
The PyPI package `eclipse-transformer` does not exist. Eclipse Transformer is a Java tool.
`analyze_impact` will shell out to run it as a subprocess using the transformer JAR (either
downloaded on first use or located via a user-supplied path). The `pyproject.toml` therefore does
NOT need a new Python dependency — but `analyze_impact` must accept a `transformer_jar_path`
parameter and document the JDK 11+ requirement clearly in the tool docstring.

**Todo List**
1. Create `tools/jakarta-impact/` directory (via file creation).
2. Write `jakarta_impact_server.py` stub: imports, shared helpers (`EXCLUDED_DIR_NAMES`,
   `_iter_files`), `mcp = FastMCP("jakarta-impact-server")`, two `@mcp.tool()` stubs, `mcp.run()`.
3. Create `tools/jakarta-impact/README.md` placeholder.
4. No `pyproject.toml` change needed — confirm in plan review.

**Relevant Context**
- Pattern to follow: [`jakarta_discovery_server.py`](tools/jakarta-discovery/jakarta_discovery_server.py:1)
- Workspace deps: [`pyproject.toml`](pyproject.toml:1)

**Status** `[ ] pending`

---

## Sub-Task 2 — Implement `analyze_impact`

**Intent**
Implement the Layer A tool that shells out to Eclipse Transformer, captures its output, then
cross-references findings against a Discovery report to produce a per-file rewrite verdict.

**Expected Outcomes**
The tool accepts:
- `war_path` — path to the pre-built WAR file
- `discovery_report_path` — path to the JSON file produced by the discovery server
  (contains `file_details` key from `scan_javax_usage`)
- `transformer_jar_path` — absolute path to `org.eclipse.transformer.cli-*.jar`
- `jdk_home` (optional) — override for the JDK to use; defaults to `JAVA_HOME` env var

It returns `impact-facts.json`-shaped output (as a Python dict):
```json
{
  "tool_version": "1.0",
  "war_path": "<abs path>",
  "transformer_ran": true,
  "transformer_exit_code": 0,
  "transformer_stderr": "",
  "file_verdicts": {
    "src/main/java/com/example/MyServlet.java": {
      "war_relative_path": "WEB-INF/classes/com/example/MyServlet.class",
      "verdict": "mechanically_rewritten",
      "changed_entries": ["WEB-INF/classes/com/example/MyServlet.class"]
    }
  },
  "out_of_scope": {
    "server_xml": "server.xml is not packaged into the WAR — Liberty runtime config is out of scope for Transformer analysis",
    "behavioral_changes": "EE9→EE10 behavioral changes are not detectable by namespace rewriting",
    "third_party_jars": "Third-party JARs bundled in WEB-INF/lib are not cross-referenced against Discovery source findings"
  },
  "skipped": []
}
```

**WAR path mapping rules (the non-trivial part):**
| Source file type | WAR-relative path |
|---|---|
| `src/main/java/com/example/Foo.java` | `WEB-INF/classes/com/example/Foo.class` |
| `src/main/webapp/WEB-INF/web.xml` | `WEB-INF/web.xml` |
| `src/main/resources/META-INF/persistence.xml` | `WEB-INF/classes/META-INF/persistence.xml` |
| `src/main/webapp/WEB-INF/faces-config.xml` | `WEB-INF/faces-config.xml` |

These rules are implemented as a deterministic function `_source_to_war_path(source_rel: str) -> str | None` that returns `None` for paths it cannot map (e.g. `server.xml`).

**Eclipse Transformer execution:**
1. Extract the WAR to a temp directory using Python's `zipfile` module.
2. Run: `java -jar <transformer_jar> <extracted_dir> <output_dir> --overwrite`
3. Diff the two directories by listing entries that differ in content (binary compare).
4. The set of differing entries = `changed_entries`.

**Cross-reference logic:**
For each source file in `discovery_report.file_details`:
- Map it to a WAR-relative path using `_source_to_war_path`.
- If mapping returned `None` → verdict `"not_in_war"` (e.g. server.xml).
- If the WAR-relative path is in `changed_entries` → `"mechanically_rewritten"`.
- If the WAR-relative path exists in the WAR but NOT in `changed_entries` → `"not_rewritten"`.
- If the WAR-relative path is not found in the WAR at all → `"war_entry_missing"` (build may be stale).

**Todo List**
1. Implement `_source_to_war_path(source_rel: str) -> str | None`.
2. Implement `_run_transformer(war_path, transformer_jar, jdk_home) -> dict` — extracts WAR to
   temp dir, runs transformer subprocess, diffs output, returns
   `{"exit_code", "stderr", "changed_entries": []}`.
3. Implement `_load_discovery_report(path: str) -> dict | None`.
4. Implement `analyze_impact` tool body: load report → run transformer → cross-reference → build
   result dict with `file_verdicts` + `out_of_scope` block + `skipped`.
5. Guard: if `JAVA_HOME` is not set and `jdk_home` not supplied, return error immediately — do not
   guess the JDK path.

**Relevant Context**
- [`jakarta_discovery_server.py` `scan_javax_usage`](tools/jakarta-discovery/jakarta_discovery_server.py:87) — produces the `file_details` dict this tool consumes.
- Transformer CLI reference: https://projects.eclipse.org/projects/technology.transformer

**Status** `[ ] pending`

---

## Sub-Task 3 — Implement `find_judgment_call_candidates`

**Intent**
Implement the standalone Layer A tool that pattern-matches source files for constructs that
Eclipse Transformer structurally cannot resolve — without needing a WAR or a build.

**Expected Outcomes**
The tool accepts:
- `repo_path` — path to the repository root (same as discovery tools)
- `discovery_report_path` (optional) — if supplied, limits the scan to files listed in the report

It returns:
```json
{
  "total_files_scanned": 12,
  "candidate_count": 4,
  "candidates": [
    {
      "file": "src/main/java/com/example/ReflectionUser.java",
      "line_number": 42,
      "category": "reflection_on_javax_classname",
      "snippet": "Class.forName(\"javax.persistence.EntityManager\")",
      "reason": "String literal containing a javax class name passed to Class.forName — Transformer rewrites bytecode but cannot rewrite string literals in reflection calls"
    }
  ],
  "skipped": []
}
```

**Categories detected (each is a separate compiled regex):**

| Category key | What it matches | Why Transformer cannot fix it |
|---|---|---|
| `reflection_on_javax_classname` | `Class.forName(` followed by a `"javax.` string literal on the same or next line | String literals in reflection calls are not bytecode symbol references |
| `dynamic_proxy_javax_interface` | `Proxy.newProxyInstance(` or `java.lang.reflect.Proxy` near a `javax.` string | Same — proxy interface names passed as strings |
| `spi_registration` | `META-INF/services/javax.*` file names in the repo | SPI service files use fully-qualified class names as file names and file contents |
| `custom_serialization` | `readObject` / `writeObject` / `readResolve` / `writeReplace` method signatures | Serialised class descriptors bake in the old class name — a rename changes compatibility |
| `jndi_javax_lookup` | `context.lookup(` or `InitialContext` near a `"javax.` string literal | JNDI names are runtime strings, not bytecode |

**Implementation notes:**
- Each category is an independent regex scan pass over `.java` files (and `META-INF/services/` for SPI).
- A single source line can produce multiple candidate entries (one per category match).
- This tool intentionally over-reports — false positives are Layer B's problem to triage.

**Todo List**
1. Define `JUDGMENT_CALL_PATTERNS` dict mapping category key → compiled regex.
2. Add SPI file scan: walk `META-INF/services/` directories, flag any filename starting with `javax.`.
3. Implement `find_judgment_call_candidates` tool body: iterate `.java` files, apply all patterns
   per line, collect hits, include SPI findings, return result dict.
4. If `discovery_report_path` is supplied, filter scanned files to only those listed in the report's
   `file_details` key (files already known to have javax usages).

**Relevant Context**
- [`_iter_files` helper](tools/jakarta-discovery/jakarta_discovery_server.py:25)
- Discovery report `file_details` key: [`scan_javax_usage`](tools/jakarta-discovery/jakarta_discovery_server.py:87)

**Status** `[ ] pending`

---

## Sub-Task 4 — README and output schema documentation

**Intent**
Document the server, both tools, their inputs/outputs, the WAR path mapping rules, and the
explicit out-of-scope list so that Layer B (the agent) knows exactly what facts it is reading and
what gaps it must not silently paper over.

**Expected Outcomes**
`tools/jakarta-impact/README.md` covers:
- Role of this server in the pipeline (Phase 1 — Impact Analysis, Layer A)
- Both tools with input/output tables and example JSON
- WAR path mapping table
- Out-of-scope section (server.xml, behavioral changes, third-party JARs)
- Prerequisites (JDK 11+, Eclipse Transformer JAR)
- Running instructions

**Todo List**
1. Write `tools/jakarta-impact/README.md` based on Sub-Tasks 2 and 3 final implementations.

**Relevant Context**
- Style reference: [`tools/jakarta-discovery/README.md`](tools/jakarta-discovery/README.md:1)

**Status** `[ ] pending`

---

## Open Questions / Confirmed Decisions

| # | Question | Decision |
|---|---|---|
| 1 | Eclipse Transformer PyPI wrapper? | Does not exist — tool shells out via `subprocess` to the JAR directly. |
| 2 | Transformer output format — does it produce a log of changed entries? | The transformer writes a modified copy of the WAR/directory. Changed entries are determined by binary-diffing original vs. output directories. |
| 3 | `server.xml` handling in `analyze_impact` | Explicitly declared out-of-scope in the `out_of_scope` block — never silently omitted. |
| 4 | `find_judgment_call_candidates` false-positive policy | Intentional over-reporting; Layer B is responsible for triage. This is by design. |
| 5 | New Python dependency needed? | No — `zipfile` and `subprocess` are stdlib. `fastmcp` already declared. |
