---
name: ee-volution-assess
description: Use when the user wants to assess, analyse, or evaluate a Java EE project for Jakarta EE migration readiness — runs discovery, impact analysis, and migration planning to produce discovery-report.json, impact-facts.json, and migration-plan.json.
---

# EE-volution Assessment Pipeline

Run the full three-phase JavaEE → JakartaEE migration pipeline against a target Maven project
and produce all JSON artefacts. Each phase maps 1-to-1 to an MCP server tool.

```
Phase 0  Discovery      → discovery-report.json   (4 MCP tools)
Phase 1  Impact         → impact-facts.json        (1 MCP tool + Maven + Eclipse Transformer)
Phase 2  Planning       → migration-plan.json      (1 MCP tool)
```

---

## Step 0 — Collect inputs

Ask the user for the following before touching any tool (use `ask_followup_question` when any
value is missing):

| Input | Notes |
|---|---|
| `repo_path` | Absolute path to the target Maven project root. Must contain a `pom.xml`. |
| `java_home` | Absolute path to a **JDK 11+** home (JDK 17 or 19 preferred). Used only by Eclipse Transformer — not the project's compile JDK. |
| `output_dir` | Directory where all JSON reports are written. Default: `<repo_path>/jakarta-migration-reports`. Create it if it does not exist. |
| `mvn_cmd` | Maven executable. Default: `mvn`. Override only if `mvn` is not on PATH. |

Confirm all four values with the user before proceeding.

---

## Step 1 — Pre-flight checks

Before running any MCP tool:

1. Verify `repo_path` contains a `pom.xml` — if not, stop and tell the user. This pipeline is
   Maven-only; Gradle and Ant are not supported.
2. Verify `java_home` points at a valid JDK directory (`<java_home>/bin/java` must exist).
3. Verify `output_dir` exists or create it using `execute_command`:
   ```powershell
   New-Item -ItemType Directory -Force -Path "<output_dir>"
   ```
4. Check whether a WAR already exists under `<repo_path>/target/*.war` (excluding
   `*.transformed.war`). If no WAR exists, run:
   ```powershell
   & mvn package -f "<repo_path>/pom.xml" -DskipTests
   ```
   Wait for it to succeed before continuing. If it fails, report the Maven error and stop.

---

## Step 2 — Phase 0: Discovery (4 parallel MCP calls)

Call all four discovery tools in the **same turn** (they are independent):

```
mcp__jakarta-discovery_46e8__scan_javax_usage      repo_path=<repo_path>
mcp__jakarta-discovery_46e8__descriptor_audit      repo_path=<repo_path>
mcp__jakarta-discovery_46e8__scan_config_literals  repo_path=<repo_path>
mcp__jakarta-discovery_46e8__parse_dependency_tree repo_path=<repo_path>
```

After all four return, write **two files**:

**1. `<output_dir>/discovery-javax-usage.json`** — the raw `scan_javax_usage` result verbatim
(this is the file passed to `analyze_impact` in Phase 1; it must be flat at the root):

```json
{ /* exact scan_javax_usage result — no wrapper */ }
```

**2. `<output_dir>/discovery-report.json`** — merged human-readable report:

```json
{
  "stage": "discovery",
  "repoPath": "<repo_path>",
  "generatedAt": "<ISO-8601 timestamp>",
  "javaxUsage":       { /* scan_javax_usage result  */ },
  "descriptorAudit":  { /* descriptor_audit result  */ },
  "configLiterals":   { /* scan_config_literals result */ },
  "dependencyTree":   { /* parse_dependency_tree result */ }
}
```

Write both files using `write_file`.

Print a one-paragraph summary of findings:
- Total `.java` files with `javax.*` usage and top 3 spec families by count.
- Number of descriptors needing migration.
- Number of `javax.*` config literals found.
- Number of `looks_legacy` dependencies.

---

## Step 3 — Phase 1: Impact Analysis

Call the impact tool:

```
mcp__jakarta-impact_7f0e__analyze_impact
  repo_path              = <repo_path>
  discovery_report_path  = <output_dir>/discovery-javax-usage.json
  java_home              = <java_home>
  mvn_cmd                = <mvn_cmd>
  work_dir               = <repo_path>/target/jakarta-impact
```

> Pass `discovery-javax-usage.json` (the flat `scan_javax_usage` output), **not** the merged
> `discovery-report.json`. `analyze_impact` reads `file_details` at the JSON root; the merged
> report nests it under `javaxUsage` and will produce empty `sourceCoverage`.

This step resolves Eclipse Transformer JARs via Maven on first use — expect it to take 1–3 minutes
on a cold run (JARs are cached on subsequent runs).

When the tool returns, write `<output_dir>/impact-facts.json` using `write_file` with the full
returned JSON object.

Print a summary:
- Eclipse Transformer return code (0 = success).
- Source files with `javax.*`: mechanically covered vs. not mechanically covered.
- Number of judgment-call candidates and their `kind` breakdown.
- Number of descriptors found and changed by Transformer.

If `transformerRun.returnCode` is non-zero, highlight it as a warning — the impact facts may be
incomplete.

---

## Step 4 — Phase 2: Migration Planning

Call the plan tool:

```
mcp__jakarta-plan__plan_migration
  impact_report_path = <output_dir>/impact-facts.json
  out_path           = <output_dir>/migration-plan.json
```

(The tool writes the file itself via `out_path`; no `write_file` call needed unless `out_path`
is not supported in the current invocation — in that case write the returned JSON manually.)

Print the plan summary table:

| Batch | # Findings | Effort (h) |
|---|---|---|
| needs_human_input | … | … |
| foundational | … | … |
| mechanical | … | … |
| manual_remediation | … | … |
| **Total** | … | … |

---

## Step 5 — Final report

After all three phases complete successfully, produce a consolidated status message:

```
✅ EE-volution pipeline complete
   Repo            : <repo_path>
   Output directory: <output_dir>

   Artefacts produced:
     discovery-report.json   — Phase 0 discovery
     impact-facts.json       — Phase 1 impact analysis
     migration-plan.json     — Phase 2 migration planning

   Key numbers:
     javax-using source files : <N>  (<M> mechanically covered, <K> need hand edits)
     Descriptors to migrate   : <N>
     Config literals          : <N>
     Legacy dependencies      : <N>
     Judgment-call candidates : <N>
     Total migration effort   : <N.N> hours
```

---

## Error handling rules

| Situation | Action |
|---|---|
| `repo_path` has no `pom.xml` | Stop. Pipeline is Maven-only. |
| `java_home` invalid / JDK 8 | Stop. Eclipse Transformer requires JDK 11+. |
| `mvn package` fails | Stop. Impact analysis requires a built WAR. |
| Any MCP tool returns an error dict | Report the error, skip downstream phases that depend on it. Phase 0 tools are independent — a failure in one does not block the others. Phase 1 failure blocks Phase 2. |
| Transformer `returnCode` ≠ 0 | Continue but warn the user. Impact facts are partial. |
| `out_path` write fails in plan tool | Write `migration-plan.json` manually using `write_file`. |

---

## Output artefact reference

| File | Produced by | Contents |
|---|---|---|
| `discovery-javax-usage.json` | Step 2 (raw `scan_javax_usage` output) | Flat javax-usage report — passed to `analyze_impact` |
| `discovery-report.json` | Step 2 (this skill assembles) | Merged output of all 4 discovery tools |
| `impact-facts.json` | Step 3 (`analyze_impact` MCP tool) | Transformer run stats, source coverage, descriptor coverage, judgment-call candidates |
| `migration-plan.json` | Step 4 (`plan_migration` MCP tool) | Ordered batches with effort estimates |

All paths must be **absolute**. The `discovery_report_path` passed to `analyze_impact` must be the
absolute path to `discovery-javax-usage.json`; relative paths may fail depending on the server's
working directory.

---

## Notes

- The discovery tools scan only source files — compiled output under `target/` and `build/`
  is excluded automatically.
- Eclipse Transformer is resolved automatically via Maven on first use. No manual JAR download.
- `judgmentCallCandidates` are pattern matches, not confirmed risks — over-reporting is deliberate.
  Layer-B triage (human or agent judgment) decides which are real.
- `mechanical` batch findings have `effortHours: 0` — Eclipse Transformer already rewrote them.
- `needs_human_input` must be resolved **before** any automated work starts (batch index 0).
- For the complete javax→jakarta namespace mapping, Liberty feature name changes, descriptor
  version update rules, and effort formula details, see `tools/jakarta-plan/REFERENCE.md`.
