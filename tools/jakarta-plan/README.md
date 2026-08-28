# Jakarta Plan MCP Server

A [FastMCP](https://github.com/jlowin/fastmcp) server that exposes one tool for
**Phase 2 — Migration Planning** of the EE-volution JavaEE → JakartaEE pipeline.

This server is **Layer A** — it produces deterministic ordering and effort
estimates.  It never resolves a finding that requires a human decision: those
are preserved in the `needs_human_input` batch for the judgment layer above this one.

---

## Role in the pipeline

```
Phase 0  discovery-report.json   ← jakarta-discovery-server
               │
               ▼
Phase 1  impact-facts.json        ← jakarta-impact-server
               │
               ▼
Phase 2  migration-plan.json      ← this server
               │
               ▼
Phase 3  judgment layer           (future — built above this server)
```

---

## Module layout

```
tools/jakarta-plan/
├── jakarta_plan_server.py   MCP server entry point — one @server.tool() definition
├── plan_builder.py          Core logic: sequencing, batching, effort estimation
├── cli.py                   CLI entry point (python tools/jakarta-plan/cli.py …)
└── REFERENCE.md             Technical reference doc (namespaces, JDK, specs …)
                             — the judgment layer must cite this when grounding decisions

tools/run_jakarta_plan_server.py   Thin launcher (adds jakarta-plan/ to sys.path)
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | Matches workspace constraint |
| [`fastmcp`](https://github.com/jlowin/fastmcp) `>=2.14.1` | Declared in workspace `pyproject.toml` |
| `impact-facts.json` | Produced by `jakarta-impact-server`'s `analyze_impact` tool; no WAR or JDK required to run this server |

No Maven, no JDK, no WAR build required — this server reads JSON and writes JSON.

---

## Tool

### `plan_migration`

Sequences and batches the findings in `impact-facts.json` and estimates effort per finding.

**Input**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `impact_report_path` | string | ✅ | Path to `impact-facts.json` produced by `analyze_impact` |
| `out_path` | string | — | If given, the plan is also written to this file (in addition to being returned) |

**Output — `migration-plan.json` structure**

```json
{
  "stage": "migration-planning-layer-a",
  "sourceReport": "/abs/path/to/impact-facts.json",
  "summary": {
    "total_findings": 23,
    "total_effort_hours": 74.5,
    "per_batch": {
      "needs_human_input":  { "finding_count": 4,  "effort_hours": 28.5 },
      "foundational":       { "finding_count": 3,  "effort_hours": 22.6 },
      "mechanical":         { "finding_count": 12, "effort_hours": 0.0  },
      "manual_remediation": { "finding_count": 4,  "effort_hours": 23.4 }
    },
    "effort_formula": "BASE_HOURS[batch] * max(1, n^0.55)  where n=file_count; BASE_HOURS=…"
  },
  "batches": [
    {
      "name": "needs_human_input",
      "index": 0,
      "findings": [
        {
          "id": "jc-0001",
          "batch": "needs_human_input",
          "batchIndex": 0,
          "findingType": "judgment_call",
          "files": ["src/main/java/com/example/ReflectionUser.java"],
          "signals": [
            "kind: reflection_string_literal",
            "detail: Class.forName(\"javax.persistence.EntityManager\") …",
            "judgment-call kind requires human triage before automated work"
          ],
          "effortHours": 6.0,
          "formulaTrace": "6.0 * max(1, 1^0.55) = 6.0 * 1.0000 = 6.0"
        }
      ]
    }
  ]
}
```

---

## Batch order

Batches are always returned in this fixed execution order:

| Index | Name | What it contains | Base effort |
|---|---|---|---|
| 0 | `needs_human_input` | Judgment-call candidates (reflection, dynamic proxies, SPI files, custom serialisation) and any source file not handled by Eclipse Transformer that a human must review before work can be planned | 6 h/finding |
| 1 | `foundational` | Build and runtime-config artefacts: `pom.xml`, `build.gradle`, `server.xml` (Liberty feature list), `MANIFEST.MF`, BND descriptors | 4 h/finding |
| 2 | `mechanical` | Source files and descriptors fully handled by Eclipse Transformer — already rewritten, zero net-new effort | 0 h |
| 3 | `manual_remediation` | Source files requiring hand edits after foundational changes are in place | 2 h/finding |

Batch ordering is enforced by a stable integer index (`BATCH_ORDER` list in
`plan_builder.py`), not by dict insertion order or any other accident of
population sequence.

---

## Effort formula

```
effort_hours = BASE_HOURS[batch] * max(1.0, n ^ 0.55)
```

Where `n` is the number of distinct files in the finding.

The exponent `0.55` makes the scaling **strictly sub-linear for every n ≥ 1**
(not just asymptotically).  Verified at import time by `_verify_sublinearity()`,
which asserts `n^0.55 < n` for `n = 2 … 100`.  A regression in the formula will
surface as an `AssertionError` on server start, not silently in production data.

Numerical spot-check against a linear baseline:

| n (files) | linear (n) | file_scale n^0.55 | ratio scale/n |
|---|---|---|---|
| 1 | 1 | 1.00 | 1.00 |
| 2 | 2 | 1.46 | 0.73 |
| 5 | 5 | 2.30 | 0.46 |
| 10 | 10 | 3.55 | 0.35 |
| 20 | 20 | 5.48 | 0.27 |
| 50 | 50 | 10.28 | 0.21 |
| 100 | 100 | 15.85 | 0.16 |

---

## Categorisation rules

Batch assignment is **rule-based on generic signals** (file type, kind keyword) —
not tied to specific finding IDs or source paths:

| Signal | Assigned batch |
|---|---|
| `findingType == "judgment_call"` | `needs_human_input` |
| Path contains `pom.xml`, `build.gradle*`, `server.xml`, `manifest.mf`, `bnd.bnd`, `.mvn/`, `gradle/` | `foundational` |
| `transformerChanged == true` in `sourceCoverage` | `mechanical` |
| `findingType == "dependency"` | `foundational` |
| Everything else not mechanically covered | `manual_remediation` |

---

## CLI usage

```bash
# From workspace root:
python tools/jakarta-plan/cli.py \
  --impact /path/to/impact-facts.json \
  [--out   /path/to/migration-plan.json]
```

Default output path: `migration-plan.json` alongside `--impact`.

**Sample stdout:**
```
Wrote /path/to/migration-plan.json
Total findings : 23
Total effort   : 74.5 hours

Batches (execution order):
  [0] needs_human_input       4 finding(s)   28.5 h
  [1] foundational            3 finding(s)   22.6 h
  [2] mechanical             12 finding(s)    0.0 h
  [3] manual_remediation      4 finding(s)   23.4 h
```

---

## Running the MCP server

```bash
uv run python tools/run_jakarta_plan_server.py
```

The server starts in stdio transport mode (FastMCP default) and is ready to accept
MCP tool calls.

---

## Reference document

[`REFERENCE.md`](REFERENCE.md) contains the authoritative technical facts the
judgment layer must cite:

- Target JDK version and Liberty version
- Complete javax → jakarta package rename table
- XML descriptor namespace and schema version updates for every descriptor type
- IBM Liberty feature name changes
- Maven dependency version bumps (common cases)
- Notable EE9→EE10 behavioural changes not covered by Eclipse Transformer
- SPI registration file rename rules

The judgment layer's decisions are only as trustworthy as the reference they are
checked against.  Every decision that touches a namespace, version number, or
feature name must cite the relevant section and row in `REFERENCE.md`.
