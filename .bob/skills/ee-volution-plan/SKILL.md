---
name: ee-volution-plan
description: Use when the user wants to produce the final, triaged migration plan (Layer B) for a Java EE → Jakarta EE migration — reads discovery-report.json, impact-facts.json, and migration-plan.json produced by the ee-volution-assess skill and emits a final-plan.json with a risk register, sprint roadmap, work items, effort summary, and sign-off block.
---

# EE-volution Final Migration Plan (Layer B)

Transform the three Layer-A artefacts produced by the **ee-volution-assess** skill into a
single, sign-off-ready `final-plan.json` that a technical architect and a project manager can
walk through together.

```
Layer A  discovery-report.json  ─┐
Layer A  impact-facts.json       ├─▶  [this skill]  ─▶  final-plan.json
Layer A  migration-plan.json    ─┘
```

All technical decisions grounded here **must cite a specific section and row of REFERENCE.md**
(`tools/jakarta-plan/REFERENCE.md`).  Decisions not grounded in REFERENCE.md must be flagged
as `assumption` until resolved.

---

## Step 0 — Collect inputs

Ask the user for any missing values (use `ask_followup_question`):

| Input | Default | Notes |
|---|---|---|
| `output_dir` | same directory as the Layer-A artefacts | Directory that contains all three Layer-A JSON files AND where `final-plan.json` will be written. |
| `project_name` | derived from `artifactId` in discovery-report.json | Human-readable project name for report headers. |
| `assignee` | `"unassigned"` | Default assignee for work items. Can be overridden per item. |
| `sprint_capacity_hours` | `16` | Working hours per sprint used to distribute work items into sprints. |

Confirm the `output_dir` contains all three required files before proceeding.

---

## When a work item is BLOCKED — what the developer does next

> **Read this before running the skill for the first time.  Return here whenever a `blocked`
> work item appears in the output.**

A `blocked` work item means the source code contains something that automated tools cannot
safely resolve without a human decision first.  The fix loop depends on the *kind* of block:

### `serializable_class` — javax-typed field found (Outcome B)

The source file has a field whose declared type is a Jakarta EE `javax.*` class
(e.g. `javax.persistence.EntityManager`, `javax.jms.Queue`).

**What to do:**
1. Open the flagged file and change the field type from `javax.*` to the `jakarta.*` equivalent
   (mapping in `REFERENCE.md §3`).
2. Save the file.
3. **Re-run this skill** (`ee-volution-plan`) — do NOT re-run `ee-volution-assess`.
   The plan skill re-reads the source file in Step 2 and will now resolve to Outcome A
   (no block) or confirm the fix is complete.

> **Why not re-run assess?**  The assessment tools (discovery, Eclipse Transformer) scan
> imports and class files — they will still flag the file as `serializable_class` regardless
> of the field-type fix, and running Transformer burns 3–10 minutes producing identical
> output.  The field-type fix is a judgment-layer concern; the plan skill is the right tool.

### `reflection_forname` — hard-coded `Class.forName("javax.…")` string

**What to do:**
1. Replace the string literal with the `jakarta.*` equivalent in the source file.
2. **Re-run this skill** (`ee-volution-plan`).

### `spi_registration` — `META-INF/services/javax.*` filename

**What to do:**
1. Rename the file to `META-INF/services/jakarta.*` and update its contents.
2. **Re-run this skill** (`ee-volution-plan`).

### Any other block

If the blocked item is a vendor descriptor decision (e.g. `glassfish-web.xml`) or an
architectural choice (e.g. runtime selection), resolve the decision externally, then
**re-run this skill** (`ee-volution-plan`) with the decision captured in the `notes` field
of the relevant risk register entry.

---

### Re-run checklist

When re-running the plan skill after fixing a blocked item:
- The three Layer-A JSON files (`discovery-report.json`, `impact-facts.json`,
  `migration-plan.json`) do **not** need to be regenerated.
- The plan skill will re-read the source files it needs (Step 2) and produce a fresh
  `final-plan.json` and `final-plan.html` that reflect the resolved state.
- Re-use the same `out_path` so the new `final-plan.json` overwrites the old one.

---

## Step 1 — Pre-flight reads

Read all three artefacts using `read_file`:

1. `<output_dir>/discovery-report.json`
2. `<output_dir>/impact-facts.json`
3. `<output_dir>/migration-plan.json`

If any file is missing or cannot be parsed, stop and report which file is missing.

Extract and hold these values in working memory:

| Symbol | Source |
|---|---|
| `repo_path` | `discovery-report.json → repoPath` |
| `artifact_id` | last segment of `repo_path` (directory name) |
| `javax_files` | `discovery-report.json → javaxUsage.files_with_javax` |
| `spec_family_counts` | `discovery-report.json → javaxUsage.spec_family_counts` |
| `descriptors_needing_migration` | count of `discovery-report.json → descriptorAudit.details` where `needs_migration == true` |
| `config_literals_count` | `discovery-report.json → configLiterals.literal_count` |
| `legacy_deps` | `discovery-report.json → dependencyTree.dependencies` where `looks_legacy == true` |
| `transformer_rc` | `impact-facts.json → transformerRun.returnCode` |
| `source_coverage` | `impact-facts.json → sourceCoverage` |
| `descriptor_coverage` | `impact-facts.json → descriptorCoverage` |
| `judgment_calls` | `impact-facts.json → judgmentCallCandidates` |
| `scope_notes` | `impact-facts.json → scopeNotes` |
| `batches` | `migration-plan.json → batches` |
| `total_effort_layer_a` | `migration-plan.json → summary.total_effort_hours` |

---

## Step 2 — Triage judgment-call candidates → Risk Register

For each entry in `judgment_calls`, produce a `RISK-NNN` record following these rules:

### `serializable_class` kind

**Before producing any risk or work item, read the source file** using `read_file` and scan its
field declarations for any type that starts with `javax.`:

- Fields whose type is a **Java SE `javax.*` package** (e.g. `javax.sql.*`, `javax.naming.*`,
  `javax.crypto.*`) — these stay `javax.*` after migration; they are **not** a risk.
- Fields whose type is a **Jakarta EE `javax.*` package** (e.g. `javax.persistence.EntityManager`,
  `javax.jms.Queue`, `javax.faces.*`) — these must become `jakarta.*`; this IS a risk.

**After reading the file, apply one of two outcomes:**

**Outcome A — no javax-typed fields found (or only Java SE javax fields):**
- Do NOT produce a `needs_human_input` work item.
- Add to the risk register with `severity: low`, `classification: pre-existing-latent-defect`,
  and note `"Field audit complete — no javax EE-typed fields found; no action required."`.
- The corresponding work item (if any) goes into `manual_remediation` batch with
  `status: "pending"` and `effortHours: 0` — it is informational only.

**Outcome B — one or more Jakarta EE javax-typed fields found:**
- Add to risk register with `severity: high`, `classification: migration-introduced-risk`.
- Resolution: "Update field type(s) `<list the specific fields>` to jakarta.* equivalents
  after foundational dependency bumps land."
- Work item goes into `needs_human_input` batch with `status: "blocked"`.

- **Reference:** `REFERENCE.md §2 (Java SE packages)`

### `reflection_forname` kind

- **Classification:** `migration-introduced-risk` — `Class.forName("javax.…")` strings are NOT
  renamed by Eclipse Transformer.
- **Severity:** `high`
- **Resolution:** "Replace the hard-coded string literal with the `jakarta.*` equivalent."
- **Reference:** `REFERENCE.md §2 (String literals)`

### `spi_registration` kind

- **Classification:** `migration-introduced-risk` — `META-INF/services/javax.*` filenames are
  NOT renamed by Eclipse Transformer.
- **Severity:** `high`
- **Resolution:** "Rename the file and update its content to the jakarta.* equivalent."
- **Reference:** `REFERENCE.md §9`

### Behavioral risk entries (always add these if any of the following specs appear in `spec_family_counts`)

Add a risk entry for each applicable spec (do not duplicate if already covered by a judgment call):

| Trigger spec | Risk ID prefix | Title | Severity | Classification | Reference |
|---|---|---|---|---|---|
| `jakarta.faces.*` / `jakarta.servlet.*` | `RISK-BEH-01` | Servlet cookie SameSite / RFC 6265bis | `medium` | `behavioral-change` | `REFERENCE.md §8 item 1` |
| `jakarta.enterprise.*` / CDI | `RISK-BEH-02` | CDI 4.0 constructor injection rule tightened | `medium` | `behavioral-change` | `REFERENCE.md §8 item 2` |
| `jakarta.ejb.*` with `@Stateful` | `RISK-BEH-03` | EJB passivation default changed | `medium` | `behavioral-change` | `REFERENCE.md §8 item 3` |
| `jakarta.xml.ws.*` | `RISK-BEH-04` | JAX-WS removed from JDK 11 — explicit dep required | `high` | `dependency-gap` | `REFERENCE.md §3 High-risk specs` |
| `jakarta.xml.bind.*` | `RISK-BEH-05` | JAXB removed from JDK 11 — explicit dep required | `high` | `dependency-gap` | `REFERENCE.md §3 High-risk specs` |

---

## Step 3 — Produce Work Items

Build the `workItems` array by expanding each finding in `migration-plan.json → batches`.
Map each finding to one or more work items using the rules below.  Assign IDs sequentially:
`WI-001`, `WI-002`, …

### Batch: `foundational`

One work item **per foundational concern** (merge related dependency bumps into a single item
rather than one item per Maven coordinate):

**WI: Bump Maven dependencies to Jakarta EE 10 coordinates**
- List every `looks_legacy: true` dependency from `dependency-tree`.
- For each, specify the exact target `groupId:artifactId:version` from `REFERENCE.md §6`.
- Flag any dependency requiring an **implementation** library bump (not just API) per `REFERENCE.md §7`.
- `referenceSection: "REFERENCE.md §6"`, `effortHours: 2.0`

**WI: Update Liberty server.xml feature names**
- List every legacy feature from `descriptorAudit → details` where `descriptor_type == "Liberty Server Config"`.
- For each, specify the Jakarta EE 10 replacement from `REFERENCE.md §5`.
- `referenceSection: "REFERENCE.md §5"`, `effortHours: 0.5`

### Batch: `mechanical`

One work item: **Run Eclipse Transformer** (zero effort — already done as part of the assessment).
- List all source files from `sourceCoverage.entries` where `mechanicallyCovered: true`.
- `effortHours: 0`
- Note: "Eclipse Transformer rewrote these files during impact analysis.  Apply the transformed
  output (`*.transformed.war`) as the mechanically migrated baseline."

### Batch: `manual_remediation`

One work item per uncovered source file (i.e., `notMechanicallyCovered` entries):

**WI: Hand-edit `<filename>`**
- List the specific `javax.*` imports that must become `jakarta.*` imports from
  `discovery-report.json → javaxUsage.file_details[filename]`.
- Specify each import rename using `REFERENCE.md §3`.
- `effortHours: 1.0` per file (base; increase to `2.0` if the file has more than 10 javax imports)

**WI: Update XML descriptors** (one item per descriptor that `needs_migration: true`):
- Use the exact namespace, schema, and version values from `REFERENCE.md §4` for the
  `descriptor_type` of each descriptor.
- `effortHours: 0.25` per descriptor

**WI: Fix config string literals** (one item if `config_literals_count > 0`):
- List every entry from `configLiterals.details`.
- For each, specify the `jakarta.*` replacement string from `REFERENCE.md §3`.
- `effortHours: 0.5 * ceil(config_literals_count / 5)` (round up)

### Batch: `needs_human_input`

Only produce a work item here if Step 2 assigned **Outcome B** to the judgment-call candidate
(i.e. a Jakarta EE javax-typed field was actually found).  Cross-reference the matching
`RISK-NNN` from the risk register.  Set `status: "blocked"` and `dependsOn: []`.

Judgment-call candidates that received **Outcome A** (field audit clean) do **not** appear in
this batch and do **not** block Sprint 1.  They are recorded in the risk register as resolved
low-severity items only.

> If **all** `serializable_class` candidates resolve to Outcome A and no other `needs_human_input`
> items exist, Sprint 1 is empty — collapse the roadmap to 3 sprints (foundational → mechanical/
> manual_remediation → verification) and note this in the sprint roadmap goal.

---

## Step 4 — Build Sprint Roadmap

Distribute work items into sprints observing **batch execution order** (batch index 0 first):

```
Sprint 1  → needs_human_input  (block until all RISK-NNN items are resolved)
Sprint 2  → foundational        (pom.xml + server.xml — compile baseline)
Sprint 3  → mechanical + manual_remediation (run transformer output + hand edits)
Sprint 4  → verification        (full mvn package with target APIs; fix compile errors per REFERENCE.md §8 item 6)
```

If `sprint_capacity_hours` is exceeded within a sprint, split into Sprint N and Sprint N+1.

Each sprint entry must include:
- `sprint` (integer starting at 1)
- `goal` (one sentence)
- `workItemIds` (list of WI-NNN IDs assigned to this sprint)
- `totalEffortHours` (sum of effortHours for this sprint's work items)

---

## Step 5 — Compute Effort Summary

```
effortSummary.totalHours     = sum of all workItems[*].effortHours
effortSummary.byBatch        = { needs_human_input: N, foundational: N, mechanical: 0, manual_remediation: N }
```

Note: `mechanical` effort is always `0` — Eclipse Transformer handles those files automatically.

---

## Step 6 — Assemble and Write `final-plan.json`

Assemble the complete JSON object matching `final-plan-schema.json` (co-located in this skill
directory).  Fields:

```json
{
  "stage": "final-plan-layer-b",
  "repoPath": "<repo_path from discovery-report.json>",
  "generatedAt": "<ISO-8601 now>",
  "sourceReports": {
    "discoveryReport": "<absolute path to discovery-report.json>",
    "impactFacts":     "<absolute path to impact-facts.json>",
    "migrationPlan":   "<absolute path to migration-plan.json>"
  },
  "projectMeta": {
    "projectName":          "<project_name input>",
    "artifactId":           "<artifact_id>",
    "currentRuntime":       "<detected from server.xml or ask user>",
    "currentJavaEEVersion": "Java EE 8"
  },
  "targetPlatform": {
    "jakartaEEVersion": "Jakarta EE 10",
    "jdk":              "JDK 17",
    "runtime":          "Open Liberty 23.0.0.6+"
  },
  "riskRegister":  [ /* Step 2 output */ ],
  "workItems":     [ /* Step 3 output */ ],
  "sprintRoadmap": [ /* Step 4 output */ ],
  "effortSummary": { /* Step 5 output */ },
  "signOff": {
    "status":     "draft",
    "preparedBy": "<Bob (ee-volution-plan skill)>",
    "notes":      "Awaiting technical lead review."
  }
}
```

Write using `write_file` to `<output_dir>/final-plan.json`.

---

## Step 7 — Print Summary

After writing the file, print the following:

```
✅ EE-volution final plan (Layer B) complete
   Repo            : <repoPath>
   Output file     : <output_dir>/final-plan.json

   Risk register   : <N> risks  (<H> high/critical, <M> medium, <L> low)
   Work items      : <N> total  (<N_blocked> blocked, <N_pending> pending)
   Sprint roadmap  : <N> sprints
   Total effort    : <N.N> hours  (Layer A estimate was <total_effort_layer_a> h)

   Next step: run ee-volution-plan-report to render final-plan.json as a one-page HTML sign-off document.
```

Then offer to generate the HTML sign-off report immediately by invoking the report-rendering
logic described in the **Report Rendering** section below.

---

## Report Rendering — `final-plan.html`

When the user confirms (or says "yes, generate the report"), read `final-plan.json` and produce
`<output_dir>/final-plan.html` using `write_file`.

The report is a single self-contained HTML file (no external assets).  Render the following
sections in order:

### Header band
- Project name (h1), "Java EE → Jakarta EE 10 Migration Plan" subtitle
- Status badge: colour-coded by `signOff.status`
  - `draft` → amber background
  - `review` → blue background
  - `approved` → green background
  - `rejected` → red background
- Three-column meta strip: Prepared by | Generated at | Target runtime

### Executive Summary bar (four tiles, grey background)
- Total effort hours
- Work items count
- Risks count (high+critical in red)
- Sprints count

### Risk Register table
Columns: Risk ID | Title | Severity | Classification | Resolution | Reference
- Color-coded severity badges: critical=red, high=orange, medium=yellow, low=grey

### Sprint Roadmap
One card per sprint with: Sprint number, goal, effort hours, list of work item IDs

### Work Items table
Columns: ID | Batch | Title | Files | Effort (h) | Status | Assignee
- Batch color tags: needs_human_input=red, foundational=blue, mechanical=green, manual_remediation=orange

### Effort Summary
Simple two-column table: Batch | Hours, with a **Total** row

### Sign-Off block
Prepared by, Reviewed by, Approved by, Status, Notes — in a bordered card

### Footer
"Made with IBM Bob" — muted, 12px, centred, thin top border

Use inline CSS only.  Palette: bg `#ffffff`, surface `#f7f8fa`, border `#e5e7eb`,
text `#1f2328`, muted `#57606a`, accent `#3b82d4`.  Font: system-ui sans-serif, ~14px,
line-height 1.6.  Max content width: 900px, centred.

---

## Error handling rules

| Situation | Action |
|---|---|
| Any Layer-A file missing | Stop. List which file is missing and the expected path. |
| `migration-plan.json → batches` is empty | Build a minimal plan from `impact-facts.json` alone using the judgment-call candidates. |
| `transformer_rc` ≠ 0 | Add a `RISK-TRANSFORMER` entry in the risk register: "Eclipse Transformer run returned non-zero exit code — mechanical coverage may be incomplete." severity: `high`. |
| A judgment-call `kind` is not one of the known kinds | Produce a risk entry with `severity: medium`, `classification: migration-introduced-risk`, and `resolution: "Unknown judgment-call kind — requires manual triage."` |
| `spec_family_counts` contains `Jakarta XML Web Services 4.0 (High Risk)` | Always add `RISK-BEH-04` regardless of whether it appears as a judgment-call. |
| `spec_family_counts` contains `Jakarta XML Binding 4.0 (JAXB - JDK11+ Removal Risk)` | Always add `RISK-BEH-05` regardless of whether it appears as a judgment-call. |

---

## Output artefact reference

| File | Produced by | Contents |
|---|---|---|
| `final-plan.json` | Step 6 | Layer-B judgment plan — full schema in `final-plan-schema.json` |
| `final-plan.html` | Step 7 / Report Rendering | One-page HTML sign-off report rendered from `final-plan.json` |

All paths must be **absolute**.

---

## Notes

- This skill is Layer B.  It does NOT re-run discovery, impact analysis, or `plan_migration`.
  Those are Layer A (ee-volution-assess skill).
- Target platform values are fixed by `REFERENCE.md §1` — do not accept user overrides unless
  grounded in a reference.
- `needs_human_input` work items are always `status: "blocked"` — they cannot be started until
  the matching risk register entry is resolved.
- Effort estimates for work items supersede the Layer-A `effortHours` values — this skill's
  estimates are per-task engineering effort, not per-finding batch effort.
- For the complete javax→jakarta namespace mapping, Liberty feature name changes, descriptor
  version update rules, SPI registration rename rules, and the effort formula, see
  `tools/jakarta-plan/REFERENCE.md`.
