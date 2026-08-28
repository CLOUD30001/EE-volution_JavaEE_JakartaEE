# Jakarta Discovery MCP Server

A [FastMCP](https://github.com/jlowin/fastmcp) server that exposes four tools for **discovering JavaEE → JakartaEE migration targets** inside a Java repository. It is designed to be consumed by an AI agent or any MCP-compatible client as part of a broader migration workflow.

---

## Tools

### 1. `scan_javax_usage`

Scans all `.java` source files in a repository and maps every `javax.*` import to its corresponding Jakarta EE spec family.

**Input**

| Parameter   | Type   | Description                              |
|-------------|--------|------------------------------------------|
| `repo_path` | string | Absolute or relative path to the repository root |

**Output**

```json
{
  "total_files_scanned": 42,
  "files_with_javax": 17,
  "spec_family_counts": {
    "Jakarta Servlet 6.0": 5,
    "Jakarta Persistence 3.1": 12
  },
  "file_details": {
    "src/main/java/com/example/MyServlet.java": ["javax.servlet.http.HttpServlet"]
  },
  "skipped": []
}
```

- Java SE APIs (e.g. `javax.sql`, `javax.naming`, `javax.crypto`) are **excluded** — only Jakarta EE-governed packages are reported.
- Covers all 16 Jakarta EE spec families defined in [Migration Blueprint v3](#spec-family-mapping).

---

### 2. `descriptor_audit`

Audits deployment descriptors (`.xml`) and JSF Facelets views (`.xhtml`) for legacy namespaces and schema versions that must be updated during migration.

**Input**

| Parameter   | Type   | Description                              |
|-------------|--------|------------------------------------------|
| `repo_path` | string | Absolute or relative path to the repository root |

**Output**

```json
{
  "descriptors_found": 3,
  "details": [
    {
      "file": "src/main/webapp/WEB-INF/web.xml",
      "descriptor_type": "web.xml",
      "version": "4.0",
      "namespace": "http://xmlns.jcp.org/xml/ns/javaee",
      "needs_migration": true,
      "risk_category": "Schema Namespace Update"
    }
  ],
  "skipped": []
}
```

**Descriptor types handled**

| File / Pattern | Handling |
|---|---|
| `web.xml`, `persistence.xml`, `beans.xml`, `ejb-jar.xml`, `faces-config.xml`, `application.xml`, `webservices.xml` | Namespace + schema version check |
| `server.xml` (IBM Liberty) | Feature list parsed; `javaee-*` features flagged as legacy |
| `*.xhtml` (Facelets views) | `xmlns:*` declarations checked for legacy URIs (`javaee`, `jcp.org`, `sun.com`) |
| Vendor descriptors (`glassfish-*`, `weblogic-*`, `jboss-*`, `ibm-web-*`, `sun-web-*`) | Flagged for manual review — no automated content check |

---

### 3. `scan_config_literals`

Scans `.java`, `.properties`, `.xml`, `.yaml`, and `.yml` files for `javax.*` string literals that appear outside import statements — for example, JNDI names, persistence unit provider class names, or configuration keys hard-coded as strings.

**Input**

| Parameter   | Type   | Description                              |
|-------------|--------|------------------------------------------|
| `repo_path` | string | Absolute or relative path to the repository root |

**Output**

```json
{
  "literal_count": 4,
  "details": [
    {
      "file": "src/main/resources/persistence.xml",
      "line_number": 7,
      "matched_literal": "javax.persistence.jdbc.url",
      "spec_family": "Jakarta Persistence 3.1",
      "snippet": "<property name=\"javax.persistence.jdbc.url\" value=\"...\"/>"
    }
  ],
  "skipped": []
}
```

Import lines are intentionally excluded (those are handled by `scan_javax_usage`).

---

### 4. `parse_dependency_tree`

Parses all `pom.xml` files found in the repository and returns a complete dependency inventory. Each dependency carries a `looks_legacy` hint for dependencies whose group ID or artifact ID contains `javax`, `javaee`, `jettison`, or `jaxb`.

> **Note:** `looks_legacy` is a hint only. Deciding which dependencies actually need a Jakarta-compatible version bump is the responsibility of a downstream Impact Analysis step, not this tool.

**Input**

| Parameter   | Type   | Description                              |
|-------------|--------|------------------------------------------|
| `repo_path` | string | Absolute or relative path to the repository root |

**Output**

```json
{
  "build_systems_detected": ["Maven"],
  "maven_poms": ["pom.xml", "module-a/pom.xml"],
  "dependencies": [
    {
      "build_system": "Maven",
      "source_file": "pom.xml",
      "groupId": "javax.servlet",
      "artifactId": "javax.servlet-api",
      "version": "4.0.1",
      "scope": "provided",
      "looks_legacy": true
    }
  ],
  "skipped": []
}
```

---

## Spec Family Mapping

The following `javax.*` package prefixes are recognised and mapped to their Jakarta EE equivalents:

| Legacy Package Prefix | Jakarta EE Spec |
|---|---|
| `javax.servlet.jsp` | Jakarta Pages 3.1 |
| `javax.servlet` | Jakarta Servlet 6.0 |
| `javax.faces` | Jakarta Faces 4.0 |
| `javax.ejb` | Jakarta Enterprise Beans 4.0 |
| `javax.persistence` | Jakarta Persistence 3.1 |
| `javax.enterprise.concurrent` | Jakarta Concurrency 3.0 |
| `javax.enterprise` | Jakarta CDI 4.0 |
| `javax.inject` | Jakarta CDI 4.0 |
| `javax.interceptor` | Jakarta CDI 4.0 |
| `javax.validation` | Jakarta Bean Validation 3.0 |
| `javax.ws.rs` | Jakarta REST 3.1 |
| `javax.jws` | Jakarta XML Web Services 4.0 *(High Risk)* |
| `javax.xml.ws` | Jakarta XML Web Services 4.0 *(High Risk)* |
| `javax.jms` | Jakarta Messaging 3.1 |
| `javax.json.bind` | Jakarta JSON Binding 3.0 |
| `javax.websocket` | Jakarta WebSocket 2.1 |
| `javax.annotation` | Jakarta Annotations 2.1 *(Needs Explicit Dep)* |
| `javax.security.enterprise` | Jakarta Security 3.0 |
| `javax.xml.bind` | Jakarta XML Binding 4.0 *(JAXB – JDK 11+ Removal Risk)* |

---

## Excluded Directories

The following directories are pruned before scanning to avoid false positives from build output and downloaded runtimes:

`target`, `build`, `.git`, `node_modules`, `.gradle`, `.idea`, `.vscode`, `out`, `bin`

---

## Requirements

- Python 3.11+
- [`fastmcp`](https://github.com/jlowin/fastmcp)

Install dependencies (using [uv](https://github.com/astral-sh/uv)):

```bash
uv sync
```

---

## Running the Server

```bash
python jakarta_discovery_server.py
```

The server starts in stdio transport mode (FastMCP default) and is ready to accept MCP tool calls.
