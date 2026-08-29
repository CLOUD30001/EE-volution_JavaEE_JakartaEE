# EE-volution Migrate — Build Plan

## Prerequisites

> **Before handing this plan to Bob, the following must already be true in the workspace:**
>
> 1. `ee-volution-assess` skill has been run and produced all three Layer A reports:
>    - `jakarta-migration-reports/discovery-report.json`
>    - `jakarta-migration-reports/impact-facts.json`
>    - `jakarta-migration-reports/migration-plan.json`
> 2. `ee-volution-plan` skill has been run and produced the Layer B report:
>    - `jakarta-migration-reports/final-plan.json`
> 3. The target Maven project exists at the path recorded in `discovery-report.json → repoPath`
>    and contains a `pom.xml`.
> 4. The existing tools are present under `tools/jakarta-discovery/`, `tools/jakarta-impact/`,
>    and `tools/jakarta-plan/` — Sub-Tasks 5 and 7 import from them directly.
>
> If any of these are missing, run the upstream skills first before asking Bob to implement
> this plan.

---

## Top-Level Overview

Build **Layer C** of the EE-volution pipeline: the `ee-volution-migrate` skill and its backing
Python tooling (`tools/jakarta-migrate/`), plus a new MCP server (`jakarta-migrate-server`) that
the skill can invoke for the mechanical migration operations.

The skill:
1. Reads the Layer A + B reports (`discovery-report.json`, `impact-facts.json`, `final-plan.json`)
2. Runs pre-flight guardrails (reports present, git check, Liberty check, blockers surface)
3. Executes migration in ordered steps:
   - **Eclipse Transformer** on the source tree (`.java` files + XML descriptors)
   - **Gap-filler** for string literals, Facelets taglib URIs, JPA property keys (things
     Transformer cannot rename)
   - **`pom.xml` patcher** using a machine-readable dependency map
   - **`server.xml` patcher** using a machine-readable Liberty feature map
4. Verifies with `mvn package -DskipTests`
5. Deploys to Open Liberty via `liberty-maven-plugin` (if available)
6. Produces `migration-result.json` and `migration-result.html`

**Approach:** New Python MCP server (`jakarta-migrate-server`) following the identical
`fastmcp` + `@server.tool()` pattern used by the existing three servers. A new SKILL.md
(`ee-volution-migrate`) drives the MCP server calls plus the pre/post-flight logic.

**Scope constraints:**
- Maven projects only (same as upstream pipeline)
- Deployment only via `liberty-maven-plugin` (`mvn liberty:run`) — no standalone Liberty install required
- Blocked work items (`needs_human_input`) are surfaced but NOT skipped silently — user
  gets a single confirmation gate; non-blocked items proceed regardless
- `glassfish-web.xml` and all `needs_human_input` WIs are flagged in the result report
  as `manual_required` but do not stop the migration of other items

---

## Pipeline position

```
Layer A  ee-volution-assess   →  discovery-report.json
                                  impact-facts.json
                                  migration-plan.json

Layer B  ee-volution-plan     →  final-plan.json
                                  final-plan.html

Layer C  ee-volution-migrate  →  [applies all non-blocked WIs to source tree]
  (THIS SKILL)                    migration-result.json
                                  migration-result.html
```

---

## Sub-Tasks

---

### Sub-Task 1 — Machine-readable mapping files

**Status:** `[ ] pending`

**Intent:**
Create two JSON files under `tools/jakarta-migrate/` that encode `REFERENCE.md §5` (Liberty
feature names) and `REFERENCE.md §6 + §7` (Maven dependency coordinates + implementation
library bumps) in a machine-readable form. These are the authoritative lookup tables that
every downstream patcher reads — no patcher should hardcode a coordinate or feature name.

**Expected Outcomes:**
- `tools/jakarta-migrate/dependency_map.json` exists with entries for every `javax.*` →
  `jakarta.*` dependency known from REFERENCE.md §6 + §7, including `replace`, `remove`,
  `add`, and `version_bump` action types
- `tools/jakarta-migrate/feature_map.json` exists with every Liberty Java EE 8 feature →
  Jakarta EE 10 feature mapping from REFERENCE.md §5
- Both files are valid JSON and human-readable (pretty-printed, 2-space indent)

**Todo List:**
1. Create directory `tools/jakarta-migrate/`
2. Create `tools/jakarta-migrate/dependency_map.json`:
   - Key: `"groupId:artifactId"` string
   - Value: object with `action` (one of `replace` | `remove` | `add` | `version_bump`),
     and for `replace`/`add`: `targetGroupId`, `targetArtifactId`, `targetVersion`, `scope`;
     for `version_bump`: `targetVersion`; for `remove`: no extra fields
   - Must cover every entry from REFERENCE.md §6 (all 14 rows)
   - Must cover every entry from REFERENCE.md §7 (impl library bumps: hibernate-validator,
     jaxb-runtime, jaxws-rt)
   - Must include `add` entries for net-new dependencies (e.g., `com.sun.xml.ws:jaxws-rt`)
     that the plan identified as required but not present in the original pom.xml
   - Must include a `remove` entry for `javax.jws:javax.jws-api` (merged in EE10)
3. Create `tools/jakarta-migrate/feature_map.json`:
   - Key: legacy Liberty feature name (e.g., `"javaee-8.0"`)
   - Value: Jakarta EE 10 feature name (e.g., `"jakartaee-10.0"`)
   - Must cover all 16 rows from REFERENCE.md §5

**Relevant Context:**
- Source data: [`tools/jakarta-plan/REFERENCE.md`](tools/jakarta-plan/REFERENCE.md) §5, §6, §7
- Project's actual dependencies to verify coverage:
  [`javaee8-order-management/pom.xml`](javaee8-order-management/pom.xml)
- Project's actual server.xml:
  [`javaee8-order-management/src/main/liberty/config/server.xml`](javaee8-order-management/src/main/liberty/config/server.xml)
- `final-plan.json → WI-003` already resolved the exact coordinate decisions for this project —
  use it to cross-check the map entries

---

### Sub-Task 2 — `pom_patcher.py`

**Status:** `[ ] pending`

**Intent:**
Write a Python module that reads `dependency_map.json` and applies the correct Maven coordinate
changes to a `pom.xml` file using XML DOM manipulation (not string replacement). Each change
must be traceable back to the map entry that drove it.

**Expected Outcomes:**
- `tools/jakarta-migrate/pom_patcher.py` exists
- Exported function: `patch_pom(pom_path: Path, dep_map: dict) -> list[ChangeRecord]`
- `ChangeRecord` dataclass: `{ file, action, old_coordinate, new_coordinate, map_key }`
- Handles all four action types: `replace` (change groupId + artifactId + version + scope),
  `remove` (delete `<dependency>` element), `add` (insert new `<dependency>` element),
  `version_bump` (change version only, groupId/artifactId unchanged)
- Returns list of applied changes (empty list if nothing matched — not an error)
- Does NOT mutate the file; returns the patched XML string + change list;
  caller decides whether to write to disk
- Preserves XML formatting as much as possible (indentation, comments)
- Bumps `<maven.compiler.source>` and `<maven.compiler.target>` from `1.8` to `17`
  (Jakarta EE 10 requires JDK 17 minimum per REFERENCE.md §1)

**Todo List:**
1. Create `tools/jakarta-migrate/pom_patcher.py`
2. Define `ChangeRecord` dataclass
3. Implement `load_dependency_map(map_path: Path) -> dict` helper
4. Implement `patch_pom(pom_path: Path, dep_map: dict) -> tuple[str, list[ChangeRecord]]`
   using `xml.etree.ElementTree` (stdlib, no extra deps)
5. Handle Maven XML namespace (`xmlns="http://maven.apache.org/POM/4.0.0"`) correctly
   — ElementTree requires namespace-qualified tag names for lookup
6. For `add` actions, insert after the last existing `<dependency>` in `<dependencies>`
7. Compiler source/target bump: find `<maven.compiler.source>` and `<maven.compiler.target>`
   in `<properties>`, update both to `17`
8. Write unit-test style assertions as `# VERIFY:` comments in the file documenting
   expected behaviour

**Relevant Context:**
- Pattern: XML manipulation via stdlib only (no lxml) — keeps zero new dependencies
- Existing pattern for path handling:
  [`tools/jakarta-impact/transformer_runner.py`](tools/jakarta-impact/transformer_runner.py)
- Dependency map: `tools/jakarta-migrate/dependency_map.json` (Sub-Task 1)
- Maven XML namespace: `http://maven.apache.org/POM/4.0.0`

---

### Sub-Task 3 — `server_xml_patcher.py`

**Status:** `[ ] pending`

**Intent:**
Write a Python module that reads `feature_map.json` and updates Liberty `<featureManager>`
entries in `server.xml`. This is structurally simpler than pom_patcher — no dependency
graph, just element text replacement.

**Expected Outcomes:**
- `tools/jakarta-migrate/server_xml_patcher.py` exists
- Exported function: `patch_server_xml(server_xml_path: Path, feature_map: dict) -> tuple[str, list[ChangeRecord]]`
- `ChangeRecord` imported from `pom_patcher` (shared dataclass — same shape)
- Replaces each `<feature>` text that exists as a key in `feature_map` with its mapped value
- Features NOT in the map are left unchanged (and noted in change list with action `no_rule`)
- Returns patched XML string + change list (same write-to-disk responsibility as pom_patcher)
- If `<featureManager>` is absent entirely, returns unchanged XML + empty list

**Todo List:**
1. Create `tools/jakarta-migrate/server_xml_patcher.py`
2. Import `ChangeRecord` from `pom_patcher`
3. Implement `patch_server_xml(server_xml_path: Path, feature_map: dict) -> tuple[str, list[ChangeRecord]]`
4. Use `xml.etree.ElementTree` — Liberty server.xml has no default namespace so tag
   names are unqualified (simpler than pom.xml)
5. Walk all `<featureManager>/<feature>` elements, apply map
6. Return patched string + changes

**Relevant Context:**
- Liberty `server.xml` structure:
  [`javaee8-order-management/src/main/liberty/config/server.xml`](javaee8-order-management/src/main/liberty/config/server.xml)
- Feature map: `tools/jakarta-migrate/feature_map.json` (Sub-Task 1)
- `ChangeRecord` defined in Sub-Task 2's `pom_patcher.py`

---

### Sub-Task 4 — `gap_filler.py`

**Status:** `[ ] pending`

**Intent:**
Write a Python module that handles everything Eclipse Transformer does NOT cover:
string literals in Java source, JPA property keys in XML, Facelets taglib URIs in `.xhtml`,
and JSF context param names in `web.xml`. All substitutions are driven by the discovery
report's `configLiterals.details` and `descriptorAudit.details` entries — no guessing.

**Expected Outcomes:**
- `tools/jakarta-migrate/gap_filler.py` exists
- Exported function: `fill_gaps(repo_path: Path, discovery_report: dict) -> list[ChangeRecord]`
- Processes three gap categories:
  1. **Config literals** (`configLiterals.details`): for each entry, open the file, find
     the `matched_literal` string, replace it with the jakarta equivalent using the
     spec-family → namespace mapping (REFERENCE.md §3)
  2. **Facelets taglib URIs** (`descriptorAudit.details` where `descriptor_type == "Facelets View"`):
     replace legacy `xmlns.jcp.org/jsf/*` namespace URIs with `jakarta.faces.*` equivalents
     (REFERENCE.md §4 Facelets table)
  3. **SPI registrations** (scan `META-INF/services/javax.*` filenames): rename file to
     `jakarta.*` equivalent; update file contents too
- Returns list of `ChangeRecord`s — caller writes to disk
- Any literal whose target cannot be resolved from the spec map is recorded as
  `action: "manual_required"` — never silently dropped
- Does NOT write to disk itself — returns `(patched_content_by_file: dict[Path, str], changes: list[ChangeRecord])`

**Todo List:**
1. Create `tools/jakarta-migrate/gap_filler.py`
2. Define `LITERAL_MAP` — a dict mapping spec-family prefix (e.g. `"javax.jms."`) to
   `"jakarta.jms."` for all 18 families from REFERENCE.md §3
3. Define `FACELETS_URI_MAP` — maps legacy JSF Facelets URIs to Jakarta equivalents
   (all 7 rows from REFERENCE.md §4 Facelets table)
4. Implement `_patch_config_literals(repo_path, literals_details) -> dict[Path, str]`
   — reads each unique file once, applies all substitutions for that file in one pass,
   returns patched content keyed by path
5. Implement `_patch_facelets(repo_path, descriptor_details) -> dict[Path, str]`
   — for each Facelets descriptor, replaces namespace URIs
6. Implement `_rename_spi_files(repo_path) -> list[ChangeRecord]`
   — returns rename instructions (old path → new path + content update); actual rename
   done by caller
7. Implement `fill_gaps(repo_path, discovery_report) -> tuple[dict[Path, str], list[ChangeRecord]]`
   combining all three

**Relevant Context:**
- Config literals data: `discovery-report.json → configLiterals.details`
  (13 entries for this project, see [`jakarta-migration-reports/discovery-report.json`](jakarta-migration-reports/discovery-report.json))
- REFERENCE.md §3 spec map, §4 Facelets table:
  [`tools/jakarta-plan/REFERENCE.md`](tools/jakarta-plan/REFERENCE.md)
- `ChangeRecord` from Sub-Task 2

---

### Sub-Task 5 — `transformer_source_runner.py`

**Status:** `[ ] pending`

**Intent:**
Extend the existing `TransformerRunner` pattern to support running Eclipse Transformer
against a **source directory** (not a WAR). Transformer accepts a directory as both
input and output — it will recurse into it and apply Text Action to `.java` files and
XML Action to descriptor files. This module wraps that directory-mode invocation.

**Expected Outcomes:**
- `tools/jakarta-migrate/transformer_source_runner.py` exists
- Class `SourceTransformerRunner(java_home: str, work_dir: Path)` with method
  `run(source_dir: Path, mvn_cmd: str = "mvn") -> TransformSourceRun`
- `TransformSourceRun` dataclass: `{ return_code, output_dir, changed_files: list[str], unchanged_files: list[str], log_path }`
- Reuses `TransformerRunner._ensure_dependencies()` pattern (same POM template, same
  JAR cache logic) — import and delegate, do not duplicate
- Transformer is invoked with source directory as input and a **copy** under `work_dir`
  as output — source tree is NEVER modified directly by the transformer invocation
- Caller (`migrate.py`) copies the output back to source after review
- Parses transformer log to produce `changed_files` list (file paths relative to the
  source directory root)

**Todo List:**
1. Create `tools/jakarta-migrate/transformer_source_runner.py`
2. Add `from pathlib import Path; import sys; sys.path.insert(0, str(Path(__file__).parent.parent / "jakarta-impact"))`
   at top to import from sibling server directory
3. Import `TransformerRunner` from `transformer_runner` (sibling import after path addition)
4. Define `TransformSourceRun` dataclass
5. Implement `SourceTransformerRunner` class:
   - `__init__`: instantiates an internal `TransformerRunner` for dep resolution
   - `run(source_dir, mvn_cmd)`: copies source_dir to `work_dir/src-copy/`, then runs
     Transformer on that copy; output goes to `work_dir/src-transformed/`
   - Parse the log (re-use `TransformerRunner._parse_log` pattern) to extract changed files
6. Return `TransformSourceRun` from `run()`

**Relevant Context:**
- Existing transformer runner to reuse/delegate:
  [`tools/jakarta-impact/transformer_runner.py`](tools/jakarta-impact/transformer_runner.py)
- Eclipse Transformer CLI accepts directory input:
  `JakartaTransformerCLI <input-dir> <output-dir> -o -v`
- Same POM template: [`tools/pom-templates/transformer-deps-pom.xml`](tools/pom-templates/transformer-deps-pom.xml)

---

### Sub-Task 6 — `migrate.py` (orchestrator)

**Status:** `[ ] pending`

**Intent:**
Write the main orchestrator module that sequences all migration steps, manages disk
writes, collects all `ChangeRecord`s into a unified result, and produces
`migration-result.json`. This is the core business logic that the MCP server tool
will call.

**Expected Outcomes:**
- `tools/jakarta-migrate/migrate.py` exists
- Exported function:
  `run_migration(repo_path, reports_dir, java_home, mvn_cmd, work_dir, dry_run) -> MigrationResult`
- `MigrationResult` dataclass with:
  - `status`: `"success"` | `"partial"` | `"failed"`
  - `steps`: ordered list of `StepResult` (step name, status, changes, errors)
  - `skipped_items`: list of WI IDs that were `status: "blocked"` in `final-plan.json`
  - `manual_required`: list of `ChangeRecord`s with `action: "manual_required"`
  - `build_result`: `{ return_code, stdout_tail, stderr_tail }` or `None` if not run
  - `deploy_result`: `{ return_code, liberty_available: bool }` or `None` if not run
- Steps executed IN ORDER (each step's success is a prerequisite for the next):
  1. `preflight` — validate reports, surface blockers, check Git, check Liberty
  2. `transform_source` — run Eclipse Transformer on source dir
  3. `apply_transformer_output` — copy `src-transformed/` back over `src/`
  4. `gap_fill` — apply string literal + Facelets URI patches
  5. `patch_pom` — apply dependency coordinate changes
  6. `patch_server_xml` — apply Liberty feature name changes
  7. `git_commit` — commit changes if Git available (skipped if not, not an error)
  8. `build_verify` — `mvn package -DskipTests`
  9. `deploy` — `mvn liberty:run` (skipped if Liberty not detected)
- `dry_run=True` executes all read/compute steps but writes NOTHING to disk (for preview)
- Writes `migration-result.json` to `reports_dir` at the end

**Todo List:**
1. Create `tools/jakarta-migrate/migrate.py`
2. Define `StepResult`, `MigrationResult` dataclasses
3. Import `SourceTransformerRunner`, `pom_patcher`, `server_xml_patcher`, `gap_filler`
4. Implement `_preflight(repo_path, reports_dir) -> PreflightResult` with:
   - Report existence check (hard stop if missing)
   - Parse `final-plan.json` for blocked WIs — collect as `skipped_items`
   - Git check: `subprocess.run(["git", "status"])` — capture result, do not block
   - Liberty check: check if `mvn liberty:version` succeeds or
     `target/liberty/wlp/bin/server` exists — capture result, do not block
5. Implement `_write_changes(changes_by_file: dict, dry_run: bool)` — write patched
   content to disk only if `dry_run=False`
6. Implement `_git_commit(repo_path, message, dry_run)` — runs `git add -A` +
   `git commit -m "..."` if git available; returns step status
7. Implement `_run_build(repo_path, mvn_cmd)` — runs `mvn package -DskipTests`,
   returns `{ return_code, stdout_tail }` (last 50 lines of stdout)
8. Implement `_run_deploy(repo_path, mvn_cmd, deploy_available)` — runs
   `mvn liberty:run -Dliberty.env.WLP_OUTPUT_DIR=...` with a timeout, returns result;
   skipped if `deploy_available=False`
9. Implement `run_migration(...)` wiring all steps together in order
10. Implement `write_migration_result(result, out_path)` serialising `MigrationResult`
    to JSON

**Relevant Context:**
- Sub-Tasks 2–5 provide all the patchers this orchestrator calls
- `final-plan.json` WI statuses: [`jakarta-migration-reports/final-plan.json`](jakarta-migration-reports/final-plan.json)
- Pattern for subprocess + error dict: [`tools/jakarta-impact/transformer_runner.py`](tools/jakarta-impact/transformer_runner.py)
- Pattern for build output in impact analysis: `subprocess.run(capture_output=True, text=True)`

---

### Sub-Task 7 — `jakarta_migrate_server.py` (MCP server)

**Status:** `[ ] pending`

**Intent:**
Create the new MCP server that exposes one tool — `run_migration` — following the exact
same `fastmcp` pattern as the existing three servers. The server is a thin wrapper: it
validates inputs, calls `migrate.run_migration()`, and returns the `MigrationResult` as
a dict.

**Expected Outcomes:**
- `tools/jakarta-migrate/jakarta_migrate_server.py` exists
- `FastMCP` server named `"jakarta-migrate-server"` with one tool: `run_migration`
- Tool signature:
  ```python
  def run_migration(
      repo_path: str,
      reports_dir: str,
      java_home: str,
      mvn_cmd: str = "mvn",
      work_dir: str | None = None,
      dry_run: bool = False,
  ) -> dict
  ```
- Returns `MigrationResult` serialised as dict OR `{"error": "..."}` on hard failure
- Launcher script `tools/run_jakarta_migrate_server.py` follows identical pattern to
  existing launchers

**Todo List:**
1. Create `tools/jakarta-migrate/jakarta_migrate_server.py`
2. Instantiate `FastMCP("jakarta-migrate-server", version="0.1.0", instructions="...")`
3. Register `run_migration` tool with `@server.tool()` decorator
4. Inside the tool: validate `repo_path` has `pom.xml`, validate `reports_dir` has
   all three required JSON files; return `{"error": ...}` if not
5. Call `migrate.run_migration(...)` inside a `try/except`; return `{"error": str(e)}`
   on unexpected exceptions
6. Add `if __name__ == "__main__": server.run()`
7. Create `tools/run_jakarta_migrate_server.py` launcher (identical structure to
   existing launchers, pointing at `jakarta-migrate` directory)

**Relevant Context:**
- Pattern to follow exactly:
  [`tools/jakarta-impact/jakarta_impact_server.py`](tools/jakarta-impact/jakarta_impact_server.py)
  [`tools/jakarta-plan/jakarta_plan_server.py`](tools/jakarta-plan/jakarta_plan_server.py)
- Launcher pattern:
  [`tools/run_jakarta_impact_server.py`](tools/run_jakarta_impact_server.py)

---

### Sub-Task 8 — `migration-result.html` renderer

**Status:** `[ ] pending`

**Intent:**
Write a standalone renderer that reads `migration-result.json` and produces a
self-contained HTML one-pager (`migration-result.html`). Follows the same inline-CSS,
no-external-assets pattern used by `final-plan.html` from the plan skill.

**Expected Outcomes:**
- `tools/jakarta-migrate/result_renderer.py` exists
- Exported function: `render_html(result: dict, out_path: Path) -> None`
- HTML sections (in order):
  1. **Header band** — project name, "Jakarta EE 10 Migration Result" subtitle,
     status badge (success=green, partial=amber, failed=red)
  2. **Summary tiles** — 4 tiles: Steps run, Changes applied, Skipped (blocked) items,
     Manual-required items
  3. **Steps table** — Step name | Status | Changes count | Notes
  4. **Changes Applied table** — File | Action | Old value | New value | Driven by
  5. **Skipped Items** — WI ID | Title | Reason (blocked) | Risk reference
  6. **Manual Required Items** — File | Literal | Reason not auto-fixed
  7. **Build Result** — return code, last 20 lines of compiler output
  8. **Deploy Result** — Liberty available | return code | endpoint URL (if detected)
  9. **Footer** — "Made with IBM Bob"
- Same CSS palette as `final-plan.html`:
  bg `#ffffff`, surface `#f7f8fa`, border `#e5e7eb`, text `#1f2328`,
  muted `#57606a`, accent `#3b82d4`, font system-ui, max-width 900px

**Todo List:**
1. Create `tools/jakarta-migrate/result_renderer.py`
2. Implement `render_html(result: dict, out_path: Path) -> None`
3. Build HTML as an f-string (same approach as the plan skill's HTML renderer)
4. Use inline `<style>` block at top; no external CSS, no JS
5. Write file at `out_path` using `out_path.write_text(html, encoding="utf-8")`

**Relevant Context:**
- Style reference: [`jakarta-migration-reports/final-plan.html`](jakarta-migration-reports/final-plan.html)
  (read it to match the CSS palette and card layout exactly)
- `MigrationResult` JSON schema defined in Sub-Task 6

---

### Sub-Task 9 — `SKILL.md` for `ee-volution-migrate`

**Status:** `[ ] pending`

**Intent:**
Write the Bob skill file that drives Layer C. The skill reads the three Layer A+B reports,
runs the pre-flight guardrails interactively with the user (single confirmation gate for
soft blockers), calls the MCP server tool, and presents the result. Follows the structure
and conventions of the two existing SKILL.md files.

**Expected Outcomes:**
- `.bob/skills/ee-volution-migrate/SKILL.md` exists
- Skill `name: ee-volution-migrate`
- Covers all pre-flight checks with exact decision rules (hard stop vs. soft gate)
- Calls `mcp__jakarta-migrate__run_migration` tool once (all orchestration is in the server)
- Post-run: reads `migration-result.json` and prints a structured summary
- Offers to render HTML (`migration-result.html`) immediately after
- Contains a **Blockers section** explaining what each blocked WI means and how to resolve it
- Contains an **Error handling table** (same format as existing skills)

**Todo List:**
1. Create `.bob/skills/ee-volution-migrate/` directory
2. Create `SKILL.md` with YAML frontmatter (`name`, `description`)
3. **Step 0 — Collect inputs** section:
   - `repo_path` — must contain `pom.xml`
   - `reports_dir` — must contain `discovery-report.json`, `impact-facts.json`,
     `final-plan.json` (NOT `migration-plan.json` — final-plan supersedes it)
   - `java_home` — JDK 11+ (reused from assess skill)
   - `mvn_cmd` — default `mvn`
   - `dry_run` — default `false`; if `true`, no files are written, only a preview
4. **Step 1 — Pre-flight** section with exact rules:

   | Check | Type | Behaviour |
   |---|---|---|
   | `final-plan.json` present | Hard blocker | Stop, report missing file |
   | `impact-facts.json` present | Hard blocker | Stop |
   | `discovery-report.json` present | Hard blocker | Stop |
   | Any WI `status: "blocked"` | Soft gate | List blocked WIs + risks, ask "Proceed anyway?" |
   | `signOff.status == "draft"` | Advisory | Surface, do not block |
   | Git available | Soft gate | If NO: ask "Continue without Git safety checkpoint?" |
   | Liberty available (via `mvn liberty:version`) | Advisory for migration; Hard gate for deploy | Migration proceeds; deploy step is skipped + reported if Liberty absent |

5. **Step 2 — Run migration** section: call `mcp__jakarta-migrate__run_migration`
6. **Step 3 — Present result** section: structured summary from `migration-result.json`
7. **Step 4 — HTML report** section: offer to render `migration-result.html`
8. **Blockers** section: what each WI type means + what to do before re-running
9. **Error handling table** section

**Relevant Context:**
- Pattern to follow exactly:
  [`.bob/skills/ee-volution-assess/SKILL.md`](.bob/skills/ee-volution-assess/SKILL.md)
  [`.bob/skills/ee-volution-plan/SKILL.md`](.bob/skills/ee-volution-plan/SKILL.md)
- Blocked WI data: [`jakarta-migration-reports/final-plan.json`](jakarta-migration-reports/final-plan.json)
  (WI-001 and WI-002 are the two blocked items for this project)

---

### Sub-Task 10 — MCP server registration (`.bob/mcp.json`)

**Status:** `[ ] pending`

**Intent:**
Register the new `jakarta-migrate-server` in the Bob MCP configuration so the skill can
call `mcp__jakarta-migrate__run_migration` as a tool. Follows the identical registration
pattern used for the two existing MCP servers.

**Expected Outcomes:**
- `.bob/mcp.json` (or equivalent Bob MCP config file) has a new entry for
  `jakarta-migrate-server`
- Entry points to `tools/run_jakarta_migrate_server.py` via `python` command
- Server is reachable in Plan and Agent modes

**Todo List:**
1. Read the existing `.bob/mcp.json` (or Bob config file) to find the exact format
   used for the existing two servers
2. Add entry for `jakarta-migrate-server` using the same `command`/`args`/`transport`
   structure
3. Verify the `run_jakarta_migrate_server.py` launcher path matches the entry

**Relevant Context:**
- Existing server registrations for `jakarta-discovery`, `jakarta-impact`, `jakarta-plan`
  are the pattern to copy
- Check `.bob/` directory for the MCP config file name

---

## File Inventory (new files to create)

```
tools/jakarta-migrate/
  dependency_map.json           (Sub-Task 1)
  feature_map.json              (Sub-Task 1)
  pom_patcher.py                (Sub-Task 2)
  server_xml_patcher.py         (Sub-Task 3)
  gap_filler.py                 (Sub-Task 4)
  transformer_source_runner.py  (Sub-Task 5)
  migrate.py                    (Sub-Task 6)
  jakarta_migrate_server.py     (Sub-Task 7)
  result_renderer.py            (Sub-Task 8)

tools/
  run_jakarta_migrate_server.py (Sub-Task 7)

.bob/skills/ee-volution-migrate/
  SKILL.md                      (Sub-Task 9)

.bob/
  mcp.json  ← updated, not new  (Sub-Task 10)
```

## Execution Order

Sub-Tasks 1 through 6 must be completed in order (each builds on the previous).
Sub-Tasks 7 and 8 can start after Sub-Task 6.
Sub-Tasks 9 and 10 can be done in parallel after Sub-Task 7 is complete.

```
[1] Maps → [2] pom_patcher → [3] server_xml_patcher → [4] gap_filler
                                                                       ↘
                                                        [5] transformer_source_runner
                                                                       ↘
                                                        [6] migrate.py (orchestrator)
                                                                       ↘
                                                         [7] MCP server + launcher
                                                         [8] HTML renderer
                                                                       ↘
                                                         [9] SKILL.md
                                                        [10] MCP registration
```
