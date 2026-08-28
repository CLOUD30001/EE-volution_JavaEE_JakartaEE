# Jakarta Impact MCP Server

A [FastMCP](https://github.com/jlowin/fastmcp) server that exposes two tools for **Phase 1 — Impact Analysis** of the EE-volution JavaEE → JakartaEE migration pipeline.

This server is **Layer A** — it produces pure, deterministic facts. Risk classification, prioritisation, and the decision of what is automatable are the responsibility of the calling agent (Layer B).

---

## Role in the pipeline

```
Phase 0 (Discovery)  →  discovery-report.json
                               │
                               ▼
Phase 1 (Impact Analysis)  ←  this server
                               │
                               ▼
                        impact-facts.json   →  Phase 2 (Migration Planning)
```

`analyze_impact` consumes the WAR produced by your Maven build and the `discovery-report.json` produced by [`jakarta-discovery-server`](../jakarta-discovery/README.md). It delegates namespace rewriting to **Eclipse Transformer** (invoked as a subprocess via its CLI JAR) and records exactly which source files were mechanically rewritten and which were not.

`find_judgment_call_candidates` is a standalone source scanner that flags constructs no rewrite tool can resolve automatically — reflection on javax class names, dynamic proxies, custom serialisation hooks, and SPI registrations.

---

## Module layout

```
tools/jakarta-impact/
├── jakarta_impact_server.py   MCP server entry point — two @server.tool() definitions
├── report_builder.py          Orchestrates everything; produces the impact-facts.json structure
├── transformer_runner.py      Subprocess wrapper around Eclipse Transformer CLI; parses its verbose log
├── discovery_diff.py          Cross-references TransformRun against discovery-report.json per source file
├── judgment_scan.py           Regex-based scanner for constructs Transformer cannot resolve
└── cli.py                     CLI entry point (python -m cli --repo … --discovery …)
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | Matches workspace constraint |
| [`fastmcp`](https://github.com/jlowin/fastmcp) `>=2.14.1` | Declared in workspace `pyproject.toml` |
| **Maven project** (`pom.xml` at repo root) | **Maven only** — Gradle and Ant are not supported. Passing a non-Maven repo to `analyze_impact` returns an error dict immediately. Gradle/Ant support is tracked as future work at the pipeline level. |
| **JDK 11+** (ideally JDK 19+) | Required by `analyze_impact` only. JDK 8 fails with `UnsupportedClassVersionError` when loading the transformer JARs. Pass via `java_home` parameter. This is **independent** of whatever JDK the target project compiles with. |
| **Maven** (`mvn`) on PATH | Required by `analyze_impact` only. Used once to resolve the Eclipse Transformer JARs via `dependency:copy-dependencies`. Override with the `mvn_cmd` parameter. |
| Pre-built WAR under `target/` | Required by `analyze_impact` only. Run `mvn package` before calling this tool. The tool auto-discovers the first `*.war` (excluding `*.transformed.war`) under `<repo>/target/`. |

> Eclipse Transformer itself is resolved automatically on first use via Maven. No manual JAR download is required.

---

## Tools

### 1. `analyze_impact`

Runs Eclipse Transformer against the pre-built WAR (via `java -cp … JakartaTransformerCLI`), parses its verbose log, then cross-references the result against the discovery report to produce per-file coverage facts.

**Input**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `repo_path` | string | ✅ | Path to the target Maven project root (WAR must already be built under `target/`) |
| `discovery_report_path` | string | ✅ | Path to the JSON output of `jakarta-discovery-server`'s `scan_javax_usage` tool |
| `java_home` | string | ✅ | Path to a JDK 11+ home directory used to run Eclipse Transformer |
| `mvn_cmd` | string | — | Maven executable name or path (default: `mvn`) |
| `work_dir` | string | — | Scratch directory for resolved JARs, the transformed WAR, and the raw transformer log (default: `<repo>/target/jakarta-impact`) |

**Output — `impact-facts.json` structure**

```json
{
  "stage": "impact-analysis-layer-a",
  "inputWar": "/abs/path/to/app.war",
  "transformerRun": {
    "tool": "org.eclipse.transformer.cli.JakartaTransformerCLI",
    "version": "1.0.0",
    "license": "EPL-2.0 OR Apache-2.0",
    "returnCode": 0,
    "actionSummary": {
      "Class Action": { "total": 42, "unchanged": 28, "changed": 14 },
      "XML Action":   { "total": 6,  "unchanged": 2,  "changed": 4  }
    },
    "logFile": "/abs/path/to/app.transform.log"
  },
  "sourceCoverage": {
    "totalFilesWithJavax": 18,
    "mechanicallyCovered": 14,
    "notMechanicallyCovered": 4,
    "entries": [
      {
        "sourceFile": "src/main/java/com/example/MyServlet.java",
        "javaxSymbols": ["javax.servlet.http.HttpServlet"],
        "classKey": "com/example/MyServlet",
        "transformerFound": true,
        "transformerChanged": true
      },
      {
        "sourceFile": "src/main/java/com/example/ReflectionUser.java",
        "javaxSymbols": ["javax.persistence.EntityManager"],
        "classKey": "com/example/ReflectionUser",
        "transformerFound": true,
        "transformerChanged": false
      }
    ]
  },
  "descriptorCoverage": [
    {
      "sourceFile": "src/main/webapp/WEB-INF/web.xml",
      "warPath": "WEB-INF/web.xml",
      "riskCategory": "Schema Namespace Update",
      "transformerFound": true,
      "transformerChanged": true
    }
  ],
  "judgmentCallCandidates": [
    {
      "file": "src/main/java/com/example/ReflectionUser.java",
      "kind": "reflection_string_literal",
      "detail": "Class.forName(\"javax.persistence.EntityManager\") - string literal invisible to import-based tooling"
    }
  ],
  "scopeNotes": [
    "Eclipse Transformer's bundled rules cover the one-time javax->jakarta package rename plus EE8->EE9 descriptor version bumps. EE9->EE10 API/behavioral changes are NOT in scope.",
    "Third-party jars bundled under WEB-INF/lib were excluded from sourceCoverage.",
    "judgmentCallCandidates are pattern matches, not confirmed risks."
  ]
}
```

**`sourceCoverage` entry fields**

| Field | Type | Meaning |
|---|---|---|
| `sourceFile` | string | Repository-relative path from the discovery report |
| `javaxSymbols` | string[] | javax imports found by discovery |
| `classKey` | string \| null | WAR-relative class path without the `WEB-INF/classes/` prefix and without `.class` (e.g. `com/example/MyServlet`). `null` if the source path could not be mapped to a WAR entry. |
| `transformerFound` | bool | Whether Eclipse Transformer processed a class file for this source (including inner classes, matched by `$`-prefix of `classKey`) |
| `transformerChanged` | bool \| null | Whether any matched class file was changed by Transformer. `null` when `transformerFound` is `false`. |

**`descriptorCoverage` entry fields**

| Field | Type | Meaning |
|---|---|---|
| `sourceFile` | string | Repository-relative descriptor path |
| `warPath` | string \| null | WAR-relative path derived from source layout; `null` for files not packaged into the WAR (e.g. `server.xml`) |
| `riskCategory` | string \| null | Risk category carried forward from the discovery report |
| `transformerFound` | bool | Whether Transformer processed this descriptor |
| `transformerChanged` | bool \| null | Whether Transformer changed it; `null` when not found |

---

#### WAR path mapping rules

Path mapping in [`discovery_diff.py`](discovery_diff.py) follows the standard Maven WAR layout:

| Source path | WAR-relative path |
|---|---|
| `src/main/java/com/example/Foo.java` | `WEB-INF/classes/com/example/Foo` (as `classKey`; `.class` and inner-class variants matched automatically) |
| `src/main/webapp/WEB-INF/web.xml` | `WEB-INF/web.xml` |
| `src/main/webapp/WEB-INF/faces-config.xml` | `WEB-INF/faces-config.xml` |
| `src/main/resources/META-INF/persistence.xml` | `WEB-INF/classes/META-INF/persistence.xml` |
| `server.xml` / `pom.xml` / anything else | `null` → `transformerFound: false`, `transformerChanged: null` |

Unmapped paths are **never silently dropped** — they always appear in `descriptorCoverage` with `warPath: null`.

---

### 2. `find_judgment_call_candidates`

Scans Java source files for constructs that Eclipse Transformer **structurally cannot resolve**. No WAR, no build, no JDK required — runs standalone against any source tree.

> This tool intentionally over-reports. False-positive triage is the responsibility of the calling agent (Layer B).

**Input**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `repo_path` | string | ✅ | Absolute or relative path to the repository root |

**Output** — a flat list of findings (same as `judgmentCallCandidates` inside `impact-facts.json`)

```json
[
  {
    "file": "src/main/java/com/example/ReflectionUser.java",
    "kind": "reflection_string_literal",
    "detail": "Class.forName(\"javax.persistence.EntityManager\") - string literal invisible to import-based tooling"
  },
  {
    "file": "src/main/java/com/example/OrderEntity.java",
    "kind": "serializable_class",
    "detail": "implements Serializable, with custom read/write hooks - check field types by hand"
  },
  {
    "file": "src/main/resources/META-INF/services/javax.persistence.spi.PersistenceProvider",
    "kind": "spi_registration",
    "detail": "ServiceLoader registration file named after a javax interface: javax.persistence.spi.PersistenceProvider"
  }
]
```

**Detection categories (`kind` values)**

| Kind | What is matched | Why Transformer cannot fix it |
|---|---|---|
| `reflection_string_literal` | `Class.forName("javax.…")` — string literal with a javax class name | String literals are not bytecode symbol references; Transformer only rewrites bytecode imports and descriptor text |
| `dynamic_proxy` | `Proxy.newProxyInstance(…)` — any occurrence | Proxy interface names may be passed as runtime strings; requires manual verification |
| `serializable_class` | Any class that `implements Serializable` | Serialised class descriptors embed the fully-qualified class name; a javax→jakarta rename changes the serial form. The `detail` field distinguishes classes that also declare custom serialisation hooks (`readObject` / `writeObject` / `readResolve` / `writeReplace`) from those that don't. |
| `spi_registration` | `META-INF/services/javax.*` filenames under `src/main/resources/` | SPI service-file names and their entries are plain text strings, not bytecode; Transformer does not rename service files. |

> **Note on `serializable_class`:** A Serializable class is flagged even when none of its fields are javax-typed. Determining whether a field is actually javax-typed requires type resolution (AST / compiler-level analysis) which this scanner deliberately does not attempt. That triage is Layer B's job.

---

## CLI usage

Run without the MCP server for one-shot pipeline use:

```bash
python -m tools.jakarta-impact.cli \
  --repo    /path/to/legacy-app \
  --discovery /path/to/discovery-report.json \
  --java-home /usr/lib/jvm/java-19-openjdk \
  [--work-dir /tmp/jakarta-impact] \
  [--mvn    mvn] \
  [--out    /path/to/impact-facts.json]
```

**Defaults:**
- `--work-dir` → `<repo>/target/jakarta-impact`
- `--out` → `impact-facts.json` in the same directory as `--discovery`

**CLI output (stdout summary):**
```
Wrote /path/to/impact-facts.json
Source files with javax usage: 18
  mechanically covered:     14
  NOT mechanically covered: 4
Judgment-call candidates: 3
```

---

## Running the MCP server

```bash
python tools/jakarta-impact/jakarta_impact_server.py
```

The server starts in stdio transport mode (FastMCP default) and is ready to accept MCP tool calls.

---

## How Eclipse Transformer JARs are resolved

[`transformer_runner.py`](transformer_runner.py) resolves the Eclipse Transformer JARs **automatically on first use** via Maven's `dependency:copy-dependencies` goal, using a minimal POM template from `tools/pom-templates/transformer-deps-pom.xml`. Resolved JARs are cached under `<work_dir>/transformer-deps/target/dependency/` — subsequent runs skip the resolution step.

Eclipse Transformer is licensed under **EPL-2.0 OR Apache-2.0** (license chosen over OpenRewrite's Jakarta recipes specifically because it is SaaS-compatible).

---

## Explicit out-of-scope items

The following are **never** covered by this server and are always declared in the `scopeNotes` section of `impact-facts.json` rather than silently omitted:

1. **EE9→EE10 behavioural changes** — Eclipse Transformer's rules cover the one-time `javax→jakarta` package rename and EE8→EE9 descriptor version bumps. Stricter CDI rules, removed deprecated methods, the servlet cookie RFC 6265 behaviour change, and other EE9→EE10 differences are **not** detectable by this tool.
2. **Third-party JARs in `WEB-INF/lib`** — excluded from `sourceCoverage`; their javax surface is a dependency-version-bump concern already tracked in Discovery's dependency inventory.
3. **`server.xml` (IBM Liberty runtime config)** — not packaged into the WAR; appears in `descriptorCoverage` with `warPath: null` and `transformerFound: false`.
4. **`judgmentCallCandidates` are candidates, not confirmed risks** — pattern matches only; real risk confirmation is Layer B's responsibility.
