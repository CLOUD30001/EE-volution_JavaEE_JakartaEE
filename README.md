# EE-volution — Java EE → Jakarta EE Migration Agent

An **AI-powered migration pipeline** that takes a Java EE 8 Maven application to Jakarta EE 10, orchestrated by [IBM Bob](https://ibm.com/products/watson-studio). The project ships a complete Java EE 8 demo application, four FastMCP tool servers, three Bob skills, and a pre-generated set of migration reports — covering the full journey from discovery through to an applied, buildable Jakarta EE 10 codebase.

---

## Repository layout

```
.
├── javaee8-order-management/     Java EE 8 demo app (the migration target)
├── tools/
│   ├── jakarta-discovery/        MCP server — Phase 0: Discovery
│   ├── jakarta-impact/           MCP server — Phase 1: Impact Analysis
│   ├── jakarta-plan/             MCP server — Phase 2: Migration Planning
│   ├── jakarta-migrate/          MCP server — Phase 3: Automated Migration
│   └── pom-templates/            POM templates used by tools at runtime
├── .bob/
│   ├── mcp.json                  MCP server registrations for Bob
│   └── skills/
│       ├── ee-volution-assess/   Layer A skill (Discovery → Impact → Plan)
│       ├── ee-volution-plan/     Layer B skill (Final plan + risk register)
│       └── ee-volution-migrate/  Layer C skill (Apply migration to source)
├── reports/                      Pre-generated migration report artefacts
├── docs/                         Background documents
└── pyproject.toml                Python workspace (uv / FastMCP)
```

---

## The demo application

[`javaee8-order-management/`](javaee8-order-management/) is a deliberately broad Java EE 8 WAR that exercises the widest possible surface area for migration analysis. It is both a **runnable Open Liberty app** and a **migration fixture** — seeded with real-world traps that a naive `import javax.*` scanner would miss.

**Specs covered:** Servlet 4.0, JSF 2.3, EJB 3.2, JPA 2.2, CDI 2.0, Bean Validation 2.0, JAX-RS 2.1, JAX-WS 2.3, JMS 2.0, JSON-B 1.0, WebSocket 1.1, Concurrency Utilities 1.0, Java EE Security API 1.0, JAXB 2.3, Common Annotations 1.3.

### Running it

```bash
cd javaee8-order-management
mvn liberty:dev
```

Once started, Open Liberty is available at:

| Endpoint | URL |
|---|---|
| Index page | `http://localhost:9080/javaee8-order-management/` |
| JSF order form | `http://localhost:9080/javaee8-order-management/orders.xhtml` |
| JAX-RS endpoint | `http://localhost:9080/javaee8-order-management/api/orders` |
| Export servlet | `http://localhost:9080/javaee8-order-management/export/orders` |
| WebSocket | `ws://localhost:9080/javaee8-order-management/ws/order-status` |

See [`javaee8-order-management/README.md`](javaee8-order-management/README.md) for full build notes, known issues, and JMS/Liberty configuration details.

---

## The migration pipeline

The pipeline runs in four phases across three layers. Each phase maps to one MCP server tool; each layer maps to one Bob skill.

```
Layer A  ─── Phase 0  Discovery      →  discovery-report.json
         ─── Phase 1  Impact Analysis →  impact-facts.json
         ─── Phase 2  Planning        →  migration-plan.json

Layer B  ─── Judgment + Final Plan   →  final-plan.json  +  final-plan.html

Layer C  ─── Automated Migration     →  source tree changes
                                        migration-result.json  +  migration-result.html
```

### Phase 0 — Discovery (`jakarta-discovery`)

Four tools run in parallel against the source tree:

| Tool | What it produces |
|---|---|
| `scan_javax_usage` | Maps every `javax.*` import to a Jakarta EE spec family across all 16 known families |
| `descriptor_audit` | Checks XML deployment descriptors and Facelets views for legacy namespaces and schema versions |
| `scan_config_literals` | Finds `javax.*` string literals outside import statements (JNDI names, property keys, annotation values) |
| `parse_dependency_tree` | Inventories Maven dependencies and flags any that `looks_legacy` |

### Phase 1 — Impact Analysis (`jakarta-impact`)

Runs **Eclipse Transformer** against the built WAR, then cross-references its output against the discovery report to produce per-file coverage facts:

- Which source files were **mechanically covered** (fully rewritten by the transformer)
- Which were **not covered** and require hand edits
- **Judgment-call candidates** — patterns the transformer structurally cannot resolve: `Class.forName("javax.…")` reflection, dynamic proxies, `Serializable` classes, and `META-INF/services/javax.*` SPI registrations

Eclipse Transformer JARs are resolved automatically via Maven on first use — no manual download required.

### Phase 2 — Migration Planning (`jakarta-plan`)

Sequences findings into four ordered batches with sub-linear effort estimates:

| Batch | Contents | Base effort |
|---|---|---|
| `needs_human_input` | Judgment-call candidates requiring human decision first | 6 h/finding |
| `foundational` | `pom.xml`, `server.xml` — the compile baseline everything else depends on | 4 h/finding |
| `mechanical` | Files fully handled by Eclipse Transformer — zero net-new effort | 0 h |
| `manual_remediation` | Source files needing hand edits after foundational changes land | 2 h/finding |

Effort formula: `BASE_HOURS × max(1, n^0.55)` where `n` is the file count. The `0.55` exponent is strictly sub-linear for all `n ≥ 1`.

### Layer B — Final Plan (`ee-volution-plan` skill)

Reads the three Layer A artefacts and produces a `final-plan.json` containing:

- **Risk register** — triaged judgment-call candidates plus behavioral-change risks (CDI 4.0, EJB passivation, JAXB/JAX-WS JDK removal, servlet cookie changes)
- **Work items** — concrete, per-file engineering tasks with effort estimates grounded in [`REFERENCE.md`](tools/jakarta-plan/REFERENCE.md)
- **Sprint roadmap** — work items distributed across sprints respecting batch execution order
- **Sign-off block** — draft / review / approved status for architect sign-off
- **`final-plan.html`** — a one-page self-contained HTML report

### Layer C — Automated Migration (`ee-volution-migrate` skill)

Applies all non-blocked work items from `final-plan.json` in nine sequential steps:

1. Pre-flight validation
2. Run Eclipse Transformer on `src/main/`
3. Copy transformed source back over `src/main/`
4. Gap-fill: string literals, Facelets namespace URIs, SPI file renames
5. Patch `pom.xml` dependency coordinates
6. Patch Liberty `server.xml` feature names
7. Git commit
8. `mvn package -DskipTests`
9. `mvn liberty:run`

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | MCP servers and skills |
| [uv](https://github.com/astral-sh/uv) | latest | Dependency management |
| Maven | 3.8+ | Project builds and Eclipse Transformer JAR resolution |
| JDK | 17+ | For running Eclipse Transformer (impact analysis); the demo app compiles to JDK 17 bytecode |
| IBM Bob | latest | Agent runtime that hosts the MCP servers and skills |

---

## Setup

### 1. Install Python dependencies

```bash
uv sync
```

### 2. Register the MCP servers with Bob

The servers are already declared in [`.bob/mcp.json`](.bob/mcp.json) and will start automatically when Bob loads. All four servers use `uv run python <entry-point>` and require no separate installation step.

### 3. Build the demo app (required for impact analysis)

```bash
mvn package -f javaee8-order-management/pom.xml -DskipTests
```

---

## Running the pipeline in Bob

Open this repository in IBM Bob. The three skills become available automatically.

### Assess (Layer A)

Ask Bob:

> *"Assess `javaee8-order-management` for Jakarta EE migration readiness"*

Bob will activate the **ee-volution-assess** skill, run all four discovery tools in parallel, invoke Eclipse Transformer via the impact server, produce the migration plan, and summarise findings.

### Plan (Layer B)

Ask Bob:

> *"Produce the final migration plan"*

Bob activates **ee-volution-plan**, triages judgment-call candidates, builds the risk register and sprint roadmap, writes `final-plan.json`, and offers to render `final-plan.html`.

### Migrate (Layer C)

Ask Bob:

> *"Apply the migration"*

Bob activates **ee-volution-migrate**, runs the nine-step migration tool, and reports on each step including build output.

---

## Pre-generated reports

[`reports/`](reports/) contains a complete set of migration artefacts produced against the demo application:

| File | Phase | Contents |
|---|---|---|
| [`discovery-report.json`](reports/discovery-report.json) | Phase 0 | Merged output of all four discovery tools |
| [`discovery-javax-usage.json`](reports/discovery-javax-usage.json) | Phase 0 | Raw `scan_javax_usage` output (passed to impact analysis) |
| [`impact-facts.json`](reports/impact-facts.json) | Phase 1 | Eclipse Transformer results, source coverage, judgment-call candidates |
| [`migration-plan.json`](reports/migration-plan.json) | Phase 2 | Batched findings with effort estimates |
| [`final-plan.json`](reports/final-plan.json) | Layer B | Risk register, work items, sprint roadmap, sign-off block |
| [`migration-result.json`](reports/migration-result.json) | Layer C | Step-by-step migration execution results |
| [`migration-result.html`](reports/migration-result.html) | Layer C | Self-contained HTML migration summary |

---

## Tool server reference

| Server | Entry point | MCP tools |
|---|---|---|
| `jakarta-discovery` | [`tools/jakarta-discovery/jakarta_discovery_server.py`](tools/jakarta-discovery/jakarta_discovery_server.py) | `scan_javax_usage`, `descriptor_audit`, `scan_config_literals`, `parse_dependency_tree` |
| `jakarta-impact` | [`tools/run_jakarta_impact_server.py`](tools/run_jakarta_impact_server.py) | `analyze_impact`, `find_judgment_call_candidates` |
| `jakarta-plan` | [`tools/run_jakarta_plan_server.py`](tools/run_jakarta_plan_server.py) | `plan_migration` |
| `jakarta-migrate` | [`tools/run_jakarta_migrate_server.py`](tools/run_jakarta_migrate_server.py) | `run_migration` |

Each server can also be invoked standalone without Bob via its CLI entry point. See the individual `README.md` in each tool directory for details.

---

## Skill reference

| Skill | Layer | Produces |
|---|---|---|
| [`ee-volution-assess`](.bob/skills/ee-volution-assess/SKILL.md) | A | `discovery-report.json`, `impact-facts.json`, `migration-plan.json` |
| [`ee-volution-plan`](.bob/skills/ee-volution-plan/SKILL.md) | B | `final-plan.json`, `final-plan.html` |
| [`ee-volution-migrate`](.bob/skills/ee-volution-migrate/SKILL.md) | C | `migration-result.json`, `migration-result.html` |

---

## Technical reference

[`tools/jakarta-plan/REFERENCE.md`](tools/jakarta-plan/REFERENCE.md) is the authoritative source of truth for migration decisions — target JDK and Liberty versions, the complete `javax → jakarta` package rename table, XML descriptor namespace and schema version updates, Liberty feature name changes, Maven dependency coordinate bumps, and known EE9→EE10 behavioural changes. Every decision made by the Layer B skill cites a specific section of this document.
