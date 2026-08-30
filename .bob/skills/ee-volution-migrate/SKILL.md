---
name: ee-volution-migrate
description: Use when the user wants to apply the Java EE → Jakarta EE migration to a Maven project's source tree — runs Eclipse Transformer, fills string-literal and Facelets-URI gaps, patches pom.xml and Liberty server.xml, optionally builds and deploys, and produces migration-result.json and migration-result.html.
---

# EE-volution Migration (Layer C)

Apply all non-blocked work items from the Layer B plan to the source tree and produce
`migration-result.json` + `migration-result.html`.

```
Layer A  discovery-report.json  ─┐
Layer A  impact-facts.json       │
Layer B  final-plan.json        ─┘  [this skill]  →  source tree changes
                                                       migration-result.json
                                                       migration-result.html
```

---

## Step 0 — Collect inputs

Ask the user for any missing values (use `ask_followup_question`):

| Input | Default | Notes |
|---|---|---|
| `repo_path` | — | Absolute path to the Maven project root.  Must contain a `pom.xml`. |
| `reports_dir` | same directory as Layer A/B artefacts | Must contain `discovery-report.json`, `impact-facts.json`, and `final-plan.json`. **Not** `migration-plan.json` — `final-plan.json` supersedes it. |
| `java_home` | — | Absolute path to a **JDK 11+** home (JDK 17 or 19 preferred). Used only by Eclipse Transformer. |
| `mvn_cmd` | `mvn` | Maven executable. Override only if `mvn` is not on PATH. |
| `dry_run` | `false` | If `true`, all read/compute steps run but nothing is written to disk and no git commit, build, or deploy is performed. Use for previewing changes. |

Confirm all values before proceeding to pre-flight.

---

## Step 1 — Pre-flight checks

Run each check in order.  Hard blockers stop the skill immediately; soft gates require
user confirmation before proceeding; advisories are surfaced but do not block.

| Check | Type | Behaviour |
|---|---|---|
| `final-plan.json` present | **Hard blocker** | Stop. Report the missing file and instruct the user to run `ee-volution-plan` first. |
| `impact-facts.json` present | **Hard blocker** | Stop. |
| `discovery-report.json` present | **Hard blocker** | Stop. Instruct the user to run `ee-volution-assess` first. |
| `repo_path/pom.xml` present | **Hard blocker** | Stop. Pipeline is Maven-only. |
| Any WI `status: "blocked"` in `final-plan.json` | **Soft gate** | List the blocked WI IDs and their titles. Ask: "Proceed? Blocked items will be skipped and flagged in the result report as manual_required." |
| `signOff.status == "draft"` | **Advisory** | Surface the draft status. Do not block. |
| Git available | **Soft gate** | If Git is NOT available, ask: "Continue without a Git safety checkpoint? Changes will not be committed automatically." |
| Liberty available | **Advisory for migration; Hard gate for deploy** | Migration proceeds regardless. If Liberty is absent, the `deploy` step will be skipped and reported in the result. |

**Extracting blocked WIs:**  Read `final-plan.json → workItems` where `status == "blocked"`.  For each, show: `WI-ID | title | dependsOn`.

---

## Step 2 — Run migration

Call the MCP tool:

```
mcp__jakarta-migrate__run_migration
  repo_path   = <repo_path>
  reports_dir = <reports_dir>
  java_home   = <java_home>
  mvn_cmd     = <mvn_cmd>
  dry_run     = <dry_run>
```

This tool runs all nine steps internally:

| # | Step | Description |
|---|---|---|
| 1 | `preflight` | Validate reports, collect blocked WI IDs, check Git + Liberty |
| 2 | `transform_source` | Run Eclipse Transformer on `src/main/` (output to `target/jakarta-migrate/transformer/`) |
| 3 | `apply_transformer_output` | Copy transformed source back over `src/main/` |
| 4 | `gap_fill` | Replace `javax.*` string literals, Facelets namespace URIs, rename SPI files |
| 5 | `patch_pom` | Update Maven dependency coordinates (`dependency_map.json`) |
| 6 | `patch_server_xml` | Update Liberty feature names (`feature_map.json`) |
| 7 | `git_commit` | `git add -A && git commit` (skipped if Git unavailable) |
| 8 | `build_verify` | `mvn package -DskipTests` |
| 9 | `deploy` | `mvn liberty:run` (skipped if Liberty unavailable or `dry_run=True`) |

The tool also writes `migration-result.json` to `reports_dir` automatically.

If the tool returns `{"error": "..."}`, report the error and stop.

---

## Step 3 — Present result

After the tool returns, print a structured summary:

```
✅/⚠️/❌ EE-volution migration complete
   Repo      : <repo_path>
   Status    : <status>  (success | partial | failed)
   Dry run   : <true/false>

   Steps:
     preflight            <status>
     transform_source     <status>  (<N> files changed by Transformer)
     apply_transformer    <status>
     gap_fill             <status>  (<N> files patched, <M> SPI renames)
     patch_pom            <status>  (<N> pom.xml changes)
     patch_server_xml     <status>  (<N> features updated)
     git_commit           <status>
     build_verify         <status>  (exit code <rc>)
     deploy               <status>

   Skipped (blocked WIs) : <list of WI IDs or "none">
   Manual required        : <count> items  (see migration-result.json for details)
   Result artefact        : <reports_dir>/migration-result.json
```

For any step that `"failed"`, print the error messages from `steps[*].errors`.

If `build_result.return_code != 0`, print the last 20 lines of `build_result.stdout_tail`
so the user can see the compile errors.

---

## Step 4 — HTML report

After presenting the text summary, ask:

> "Shall I render `migration-result.html` — a self-contained one-page HTML report with
> all steps, changes applied, skipped items, and build output?"

If the user says yes (or equivalent): read `<reports_dir>/migration-result.json` and
call `result_renderer.render_html(result_dict, out_path)` by executing:

```powershell
& uv run python -c "
import sys, json
from pathlib import Path
sys.path.insert(0, 'tools/jakarta-migrate')
from result_renderer import render_html
result = json.loads(Path('<reports_dir>/migration-result.json').read_text())
render_html(result, Path('<reports_dir>/migration-result.html'))
print('HTML report written.')
"
```

Replace `<reports_dir>` with the actual absolute path.

Confirm the file was written, then report:

```
✅ migration-result.html written to <reports_dir>/migration-result.html
```

---

## Blockers — what they mean and what to do

When the pre-flight soft gate surfaces blocked WIs, or when `migration-result.json`
contains `manual_required` items, the user must resolve them before a complete
migration can be certified:

### WI blocked with `serializable_class`

A `Serializable` class has a field whose declared type is a Jakarta EE `javax.*` class.

**What to do:**
1. Open the flagged file.
2. Change the field type from `javax.*` to `jakarta.*` (mapping in `REFERENCE.md §3`).
3. **Re-run `ee-volution-plan`** (Layer B) to update `final-plan.json`.
4. Re-run this skill.

### WI blocked with `reflection_forname`

Hard-coded `Class.forName("javax.…")` string that Eclipse Transformer cannot rename.

**What to do:**
1. Replace the string literal with the `jakarta.*` equivalent.
2. Re-run this skill (no need to re-run Layer A or B — the literal substitution is in `gap_fill`).

### WI blocked with `spi_registration`

A `META-INF/services/javax.*` filename.  The `gap_fill` step handles these automatically
if they are under the standard `src/main/resources/META-INF/services/` path.  If the file
is at a non-standard path, it will appear as `manual_required`.

**What to do:**
1. Rename the file manually to `META-INF/services/jakarta.*`.
2. Update the file contents (class names inside it) to use `jakarta.*`.

### WI blocked due to vendor descriptor (`glassfish-web.xml`)

GlassFish-specific deployment descriptors have no automatic Jakarta EE 10 equivalent.

**What to do:**
1. Remove `glassfish-web.xml` if it is only present for namespace declarations.
2. Or replace with an Open Liberty-equivalent descriptor.
3. Document the decision, then re-run.

### Advisory: `signOff.status == "draft"`

The plan has not been reviewed and approved.  This is an advisory only — migration
proceeds, but the output report carries `draft` status.

---

## Error handling table

| Situation | Action |
|---|---|
| `repo_path` has no `pom.xml` | **Stop.** Pipeline is Maven-only. |
| Any Layer A/B file missing | **Stop.** Report which file is missing and the correct upstream skill to run. |
| MCP tool returns `{"error": "..."}` | **Stop.** Report the error verbatim. |
| `steps[*].status == "failed"` for `transform_source` | Warn. Continue remaining steps — Transformer failure means source is NOT in the Jakarta namespace yet. Highlight in the result. |
| `steps[*].status == "failed"` for `build_verify` | Report build errors. Show stdout_tail. The source has been migrated but does not compile cleanly — hand-edit remaining compile errors per `REFERENCE.md §8 item 6`. |
| `steps[*].status == "failed"` for `deploy` | Report liberty:run failure. Migration changes are written; only the server start failed. |
| `manual_required` items in result | List them in Step 3 summary. The migration is `partial`, not `failed` — all automatable steps ran. |
| `dry_run=True` + changes expected | Confirm all steps show "skipped" for write/commit/build/deploy and that the result status is consistent with a dry run. |

---

## Output artefact reference

| File | Produced by | Contents |
|---|---|---|
| `migration-result.json` | Step 2 (`run_migration` MCP tool) | Full MigrationResult: steps, changes, skipped items, manual_required, build/deploy results |
| `migration-result.html` | Step 4 (rendered by this skill on request) | Self-contained one-page HTML summary |

All paths are **absolute**.

---

## Notes

- This skill is Layer C.  It does NOT re-run discovery, impact analysis, plan_migration,
  or ee-volution-plan.  Those are Layers A and B.
- Target platform values are fixed by `REFERENCE.md §1` — JDK 17, Jakarta EE 10.
- `needs_human_input` / blocked work items are surfaced but NOT silently skipped — the
  user receives a single confirmation gate (Step 1 soft gate).
- After migration, it is normal to have one or more `manual_required` items — this means
  the migration is `partial`, not `failed`.  A `failed` status means a hard step error
  (Transformer, build, or write failure) that requires attention before proceeding.
- For the complete javax→jakarta namespace mapping, Liberty feature name changes,
  descriptor version update rules, and SPI registration rename rules, see
  `tools/jakarta-plan/REFERENCE.md`.
