# Jakarta EE Migration Reference

Technical reference for the EE-volution migration pipeline.  This document is
the authoritative source of truth that the judgment layer **must** cite when it
pins down a technical decision — e.g. "the correct target namespace for
persistence.xml is X" or "the target JDK version is Y".  Decisions that are not
grounded in a specific entry here should be flagged as assumptions until resolved.

---

## 1. Target platform

| Property | Value |
|---|---|
| Source baseline | Java EE 8 (on IBM WebSphere Liberty or Open Liberty) |
| Target baseline | **Jakarta EE 10** |
| Target JDK | **JDK 17** (minimum; JDK 21 preferred for LTS) |
| Target runtime | Open Liberty 23.0.0.6+ (first release with full Jakarta EE 10 certification) |

> Eclipse Transformer is run on **JDK 11+** (JDK 19 recommended).  This is the
> JDK used only for the transformer tool itself; the application can target JDK 17
> for compilation.

---

## 2. javax → jakarta package rename

The rename is one-time and mechanical.  All `javax.*` packages governed by
Jakarta EE (see §3) become `jakarta.*`.  Java SE-managed packages stay `javax.*` —
do **not** rename them.

### Java SE packages that must remain `javax.*`

| Category | Packages |
|---|---|
| Database & Naming | `javax.sql` (JDBC), `javax.naming` (JNDI) |
| Security & Net | `javax.crypto`, `javax.net.ssl`, `javax.security.auth`, `javax.security.sasl` |
| XML Parsing (JAXP) | `javax.xml.parsers`, `javax.xml.transform`, `javax.xml.namespace`, `javax.xml.xpath`, `javax.xml.datatype` |
| Management & System | `javax.management` (JMX), `javax.script`, `javax.tools`, `javax.smartcardio`, `javax.swing` |

Eclipse Transformer covers the rename automatically for compiled class files and
a subset of descriptors.  The following are **not** handled by Transformer and
require hand edits:

- String literals: `Class.forName("javax.…")`
- SPI registration file names under `META-INF/services/`
- JSF context parameters (e.g. `javax.faces.PROJECT_STAGE` → `jakarta.faces.PROJECT_STAGE`)
- JPA property keys (e.g. `javax.persistence.schema-generation.database.action`)
- Annotation string values (e.g. `@ActivationConfigProperty(propertyValue = "javax.jms.Queue")`)

---

## 3. Spec family mapping (javax → jakarta)

| Legacy prefix | Jakarta EE 10 spec | Jakarta package |
|---|---|---|
| `javax.servlet.jsp.*` | Jakarta Pages 3.1 | `jakarta.servlet.jsp.*` |
| `javax.servlet.*` | Jakarta Servlet 6.0 | `jakarta.servlet.*` |
| `javax.faces.*` | Jakarta Faces 4.0 | `jakarta.faces.*` |
| `javax.ejb.*` | Jakarta Enterprise Beans 4.0 | `jakarta.ejb.*` |
| `javax.persistence.*` | Jakarta Persistence 3.1 | `jakarta.persistence.*` |
| `javax.enterprise.concurrent.*` | Jakarta Concurrency 3.0 | `jakarta.enterprise.concurrent.*` |
| `javax.enterprise.*` | Jakarta CDI 4.0 | `jakarta.enterprise.*` |
| `javax.inject.*` | Jakarta CDI 4.0 (via Jakarta Inject) | `jakarta.inject.*` |
| `javax.interceptor.*` | Jakarta CDI 4.0 | `jakarta.interceptor.*` |
| `javax.validation.*` | Jakarta Bean Validation 3.0 | `jakarta.validation.*` |
| `javax.ws.rs.*` | Jakarta REST 3.1 | `jakarta.ws.rs.*` |
| `javax.jws.*` | Jakarta XML Web Services 4.0 | `jakarta.jws.*` |
| `javax.xml.ws.*` | Jakarta XML Web Services 4.0 | `jakarta.xml.ws.*` |
| `javax.jms.*` | Jakarta Messaging 3.1 | `jakarta.jms.*` |
| `javax.json.bind.*` | Jakarta JSON Binding 3.0 | `jakarta.json.bind.*` |
| `javax.websocket.*` | Jakarta WebSocket 2.1 | `jakarta.websocket.*` |
| `javax.annotation.*` | Jakarta Annotations 2.1 | `jakarta.annotation.*` |
| `javax.security.enterprise.*` | Jakarta Security 3.0 | `jakarta.security.enterprise.*` |
| `javax.xml.bind.*` | Jakarta XML Binding 4.0 (JAXB) | `jakarta.xml.bind.*` |

### High-risk specs (additional manual steps required)

| Spec | Risk | Required action |
|---|---|---|
| Jakarta XML Web Services 4.0 | JAX-WS was removed from JDK 11. | Add explicit `jakarta.xml.ws:jakarta.xml.ws-api:4.0.x` Maven dependency; also add a JAX-WS runtime (e.g. `com.sun.xml.ws:jaxws-rt`). |
| Jakarta XML Binding 4.0 (JAXB) | JAXB was removed from JDK 11. | Add `jakarta.xml.bind:jakarta.xml.bind-api:4.0.x` + runtime (e.g. `com.sun.xml.bind:jaxb-impl`). |
| Jakarta Annotations 2.1 | No longer bundled by default on all runtimes. | Add explicit `jakarta.annotation:jakarta.annotation-api:2.1.x` dependency. |

---

## 4. XML descriptor namespace and schema version updates

### web.xml

| Field | EE 8 value | Jakarta EE 10 value |
|---|---|---|
| Root namespace | `http://xmlns.jcp.org/xml/ns/javaee` | `https://jakarta.ee/xml/ns/jakartaee` |
| `xsi:schemaLocation` | `…web-app_4_0.xsd` | `…web-app_6_0.xsd` |
| `version` attribute | `4.0` | `6.0` |

### persistence.xml

| Field | EE 8 value | Jakarta EE 10 value |
|---|---|---|
| Root namespace | `http://xmlns.jcp.org/xml/ns/persistence` | `https://jakarta.ee/xml/ns/persistence` |
| `xsi:schemaLocation` | `…persistence_2_2.xsd` | `…persistence_3_1.xsd` |
| `version` attribute | `2.2` | `3.1` |

### beans.xml

| Field | EE 8 value | Jakarta EE 10 value |
|---|---|---|
| Root namespace | `http://xmlns.jcp.org/xml/ns/javaee` | `https://jakarta.ee/xml/ns/jakartaee` |
| `xsi:schemaLocation` | `…beans_2_0.xsd` | `…beans_4_0.xsd` |
| `version` attribute | `2.0` | `4.0` |

> **`bean-discovery-mode` — pre-existing latent defect, not a migration-introduced risk:**
> The default `bean-discovery-mode="annotated"` for an empty or unversioned `beans.xml` has
> applied since **CDI 1.1 (Java EE 7, 2013)** — it is not new to CDI 4.0 and is not triggered
> by the migration itself.  An Impact Analysis tool must classify any CDI injection failure
> caused by this rule as a *pre-existing latent defect surfaced by migration*, not a
> *migration-introduced risk*.  Any touch to `beans.xml` during migration is a natural moment
> to audit bean-discovery-mode, but the risk classification matters for the risk register.

### ejb-jar.xml

| Field | EE 8 value | Jakarta EE 10 value |
|---|---|---|
| Root namespace | `http://xmlns.jcp.org/xml/ns/javaee` | `https://jakarta.ee/xml/ns/jakartaee` |
| `xsi:schemaLocation` | `…ejb-jar_3_2.xsd` | `…ejb-jar_4_0.xsd` |
| `version` attribute | `3.2` | `4.0` |

### faces-config.xml

| Field | EE 8 value | Jakarta EE 10 value |
|---|---|---|
| Root namespace | `http://xmlns.jcp.org/xml/ns/javaee` | `https://jakarta.ee/xml/ns/jakartaee` |
| `xsi:schemaLocation` | `…web-facesconfig_2_3.xsd` | `…web-facesconfig_4_0.xsd` |
| `version` attribute | `2.3` | `4.0` |

### application.xml

> **Note:** Not listed in the Jakarta EE 10 Blueprint v3.  Values below are consistent with
> the Jakarta EE XML schema registry but are unconfirmed by the Blueprint; verify before use.

| Field | EE 8 value | Jakarta EE 10 value |
|---|---|---|
| Root namespace | `http://xmlns.jcp.org/xml/ns/javaee` | `https://jakarta.ee/xml/ns/jakartaee` |
| `xsi:schemaLocation` | `…application_8.xsd` | `…application_10.xsd` |
| `version` attribute | `8` | `10` |

### Facelets (.xhtml)

| What to change | Legacy URI | Jakarta EE 10 URI |
|---|---|---|
| JSF core tag lib (f:) | `http://java.sun.com/jsf/core` or `http://xmlns.jcp.org/jsf/core` | `jakarta.faces.core` |
| JSF HTML tag lib (h:) | `http://java.sun.com/jsf/html` or `http://xmlns.jcp.org/jsf/html` | `jakarta.faces.html` |
| JSF Facelets tag lib (ui:) | `http://java.sun.com/jsf/facelets` or `http://xmlns.jcp.org/jsf/facelets` | `jakarta.faces.facelets` |
| JSF passthrough (pt:) | `http://xmlns.jcp.org/jsf/passthrough` | `jakarta.faces.passthrough` |
| JSF composite (cc:) | `http://xmlns.jcp.org/jsf/composite` | `jakarta.faces.composite` |
| JSTL core (c:) | `http://java.sun.com/jsp/jstl/core` or `http://xmlns.jcp.org/jsp/jstl/core` | `jakarta.tags.core` |
| JSTL functions (fn:) | `http://java.sun.com/jsp/jstl/functions` or `http://xmlns.jcp.org/jsp/jstl/functions` | `jakarta.tags.functions` |

Custom Facelets taglib descriptor files (if authored): update the root namespace to
`https://jakarta.ee/xml/ns/jakartaee` and the version attribute to `3.0`.

---

## 5. IBM Liberty feature name changes

In `server.xml`, the Liberty `<featureManager>` feature names change.

| Java EE 8 feature | Jakarta EE 10 feature |
|---|---|
| `javaee-8.0` | `jakartaee-10.0` |
| `servlet-4.0` | `servlet-6.0` |
| `jpa-2.2` | `persistence-3.1` |
| `ejbLite-3.2` | `enterpriseBeans-4.0` |
| `jaxrs-2.1` | `restfulWS-3.1` |
| `jsf-2.3` | `faces-4.0` |
| `cdi-2.0` | `cdi-4.0` |
| `beanValidation-2.0` | `beanValidation-3.0` |
| `webSocket-1.1` | `websocket-2.1` |
| `jsonb-1.0` | `jsonb-3.0` |
| `jaxb-2.2` | `xmlBinding-4.0` |
| `jaxws-2.2` | `xmlWS-4.0` |
| `messaging-3.0` | `messaging-3.1` |
| `concurrent-1.0` | `concurrent-3.0` |
| `appSecurity-3.0` | `appSecurity-5.0` |
| `mpConfig-2.0` | `mpConfig-3.1` *(MicroProfile 6)* |

> The `javaee-8.0` umbrella feature is **not** available in the Jakarta EE 10
> runtime — all previously included features must be listed explicitly or the
> `jakartaee-10.0` umbrella feature used instead.

---

## 6. Maven dependency version bumps (common cases)

The following is a non-exhaustive reference.  The judgment layer must verify
exact latest versions against Maven Central for each project.

| Legacy artifact | Target Jakarta EE 10 artifact |
|---|---|
| `javax.servlet:javax.servlet-api:4.0.1` | `jakarta.servlet:jakarta.servlet-api:6.0.0` |
| `javax.persistence:javax.persistence-api:2.2` | `jakarta.persistence:jakarta.persistence-api:3.1.0` |
| `javax.faces:javax.faces-api:2.3` | `jakarta.faces:jakarta.faces-api:4.0.1` |
| `javax.ejb:javax.ejb-api:3.2` | `jakarta.ejb:jakarta.ejb-api:4.0.0` |
| `javax.ws.rs:javax.ws.rs-api:2.1.1` | `jakarta.ws.rs:jakarta.ws.rs-api:3.1.0` |
| `javax.validation:validation-api:2.0.1.Final` | `jakarta.validation:jakarta.validation-api:3.0.2` |
| `javax.xml.bind:jaxb-api:2.3.1` | `jakarta.xml.bind:jakarta.xml.bind-api:4.0.0` |
| `javax.enterprise:cdi-api:2.0` | `jakarta.enterprise:jakarta.enterprise.cdi-api:4.0.1` |
| `javax.inject:javax.inject:1` | `jakarta.inject:jakarta.inject-api:2.0.1` |
| `javax.annotation:javax.annotation-api:1.3.2` | `jakarta.annotation:jakarta.annotation-api:2.1.1` |
| `javax.jms:javax.jms-api:2.0.1` | `jakarta.jms:jakarta.jms-api:3.1.0` |
| `javax.websocket:javax.websocket-api:1.1` | `jakarta.websocket:jakarta.websocket-api:2.1.1` |
| `javax.json.bind:javax.json.bind-api:1.0` | `jakarta.json.bind:jakarta.json.bind-api:3.0.0` |
| `javaee-api:8.0` (umbrella) | `jakarta.platform:jakarta.jakartaee-api:10.0.0` |

---

## 7. Third-party implementation library compatibility

Bumping a Jakarta EE *API* artifact is not sufficient — the *implementation* library that
backs it must also be a jakarta-namespace-compatible release.  A missing or stale
implementation produces a **runtime `ClassNotFoundException`**, not a compile error, making
it a worse failure mode to catch late.

| API bumped | Implementation to check |
|---|---|
| `jakarta.validation-api` | Hibernate Validator (use `8.x` for Jakarta EE 10) |
| `jakarta.xml.bind-api` | `com.sun.xml.bind:jaxb-impl` or `org.glassfish.jaxb:jaxb-runtime` |
| `jakarta.xml.ws-api` | `com.sun.xml.ws:jaxws-rt` |
| `jakarta.faces-api` | Eclipse Mojarra (`4.x`) or MyFaces (`4.x`) |
| Any other spec API | Verify the runtime/impl jar groupId has migrated to `jakarta.*` or carries a compatible release |

> **Ant build system:** Ant projects use unmanaged `lib/` JAR directories — nothing catches a
> stale transitive dependency automatically.  Manual binary replacement and `build.xml`
> classpath updates are required.  Treat Ant-built modules as a higher effort/risk tier than
> equivalent Maven or Gradle modules.

---

## 8. Notable behavioral changes (EE9→EE10, not covered by Transformer)

These require manual verification and are **not** detectable by Eclipse Transformer:

1. **Servlet cookie `SameSite` / RFC 6265bis** — `HttpServletResponse.addCookie()`
   in Jakarta Servlet 6.0 follows stricter rules for cookie attributes.  Check any
   code that reads or writes `Set-Cookie` headers directly.
2. **CDI 4.0 — `@Inject` on constructors with no-arg fallback removed** — CDI 4.0
   makes the unambiguous constructor rule stricter.  Beans that relied on the EE 8
   relaxed rules may fail to deploy.
3. **EJB passivation default changed** — `@Stateful` beans now default to
   `passivationCapable = true`; adding `@Stateful(passivationCapable = false)` is
   now required on beans that hold non-serialisable state.
4. **`javax.security.auth.message` (JASPIC) removed from standard profile** —
   Replaced by Jakarta Authentication 3.0 (`jakarta.security.auth.message`).
5. **`@WebServiceRef` and `@EJB` injection into CDI beans** — Injection rules
   between the EJB and CDI containers were tightened in Jakarta EE 9+; verify
   cross-component injection points.
6. **Removed deprecated methods** — Many specs dropped deprecated EE8 methods in
   their EE10 versions.  Run a full `mvn package` with the target APIs on the
   classpath and review all compile errors.

---

## 9. SPI registration file renames

`META-INF/services/` files named after `javax.*` interfaces must be renamed to
`jakarta.*`.  These are plain text files — Eclipse Transformer does **not** rename
service files or their contents.

| Legacy filename | Jakarta EE 10 filename |
|---|---|
| `javax.persistence.spi.PersistenceProvider` | `jakarta.persistence.spi.PersistenceProvider` |
| `javax.faces.application.ViewHandlerWrapper` | `jakarta.faces.application.ViewHandlerWrapper` |
| `javax.ws.rs.ext.RuntimeDelegate` | `jakarta.ws.rs.ext.RuntimeDelegate` |
| `javax.enterprise.inject.spi.Extension` | `jakarta.enterprise.inject.spi.Extension` |

For any other `META-INF/services/javax.*` file, rename the file and update any
fully-qualified class names inside it to use the `jakarta.*` equivalent.

---

## 10. Tools used in this pipeline

| Tool | Version | Purpose | License |
|---|---|---|---|
| Eclipse Transformer | 1.0.0 | Mechanical javax→jakarta rename for class files and descriptors | EPL-2.0 OR Apache-2.0 |
| fastmcp | ≥2.14.1 | MCP server SDK for all pipeline servers | MIT |
| Python | ≥3.11 | Pipeline runtime | PSF |

---

## 11. Pipeline stage map

```
Phase 0  discovery-report.json   ← jakarta-discovery-server
                │
                ▼
Phase 1  impact-facts.json        ← jakarta-impact-server (analyze_impact)
                │
                ▼
Phase 2  migration-plan.json      ← jakarta-plan-server (plan_migration)   ← THIS SERVER
                │
                ▼
Phase 3  judgment layer           ← (future — built above this server)
                │
                ▼
Phase 4  automated transforms / hand-edit tickets
```

---

*This document is maintained in `tools/jakarta-plan/REFERENCE.md`.  The judgment
layer must cite a specific section number and row when it grounds a decision on an
entry here.*
