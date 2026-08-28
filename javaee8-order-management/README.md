# JavaEE8 Order Management System (Legacy)

Sample Java EE 8 servlet-based Maven WAR project, deployable on IBM/Open Liberty, used
both as a **runnable demo** and as a **fixture for the JavaEE8 → Jakarta EE 10 migration
agent** (Discovery / Impact Analysis / Migration Plan stages). Business logic is
intentionally minimal, but it exercises most Java EE 8 specs and several of the
trickier, non-import-based `javax.*` references that a naive scanner would miss.

## Running it (Open Liberty)

```bash
mvn liberty:dev
```

This downloads Open Liberty automatically (via the `liberty-maven-plugin`), starts the
server defined in [server.xml](src/main/liberty/config/server.xml), and deploys the WAR.
`mvn liberty:run` also works if you don't need dev-mode hot reload.

Once it's up:

- `http://localhost:9080/javaee8-order-management/` — index page
- `http://localhost:9080/javaee8-order-management/orders.xhtml` — JSF page (persists an `Order` via JPA on submit, backed by an embedded Derby DB)
- `http://localhost:9080/javaee8-order-management/api/orders` — JAX-RS endpoint (`POST`)
- `http://localhost:9080/javaee8-order-management/export/orders` — servlet
- `ws://localhost:9080/javaee8-order-management/ws/order-status` — WebSocket endpoint

**If you already have IBM WebSphere Liberty installed** rather than wanting Open Liberty
auto-downloaded, point the plugin at it instead by adding
`<installDirectory>${your.liberty.install.path}</installDirectory>` inside the
`liberty-maven-plugin` `<configuration>` block in [pom.xml](pom.xml).

**Verified end-to-end** against Open Liberty 26.0.0.8 / JDK 8: `mvn package liberty:create
liberty:install-feature liberty:deploy liberty:start`, then confirmed `HTTP 200` on the
index page, `orders.xhtml`, and `/export/orders`, `HTTP 201` with a persisted `Order`
(auto-incrementing `id`) on `POST /api/orders`, and `HTTP 200` on the JAX-WS
`?wsdl` endpoint. Three real bugs surfaced and were fixed during that pass — worth
knowing about since they're the kind of thing a migration agent should also catch:

1. `OrderProcessorBean` had `@javax.transaction.Transactional` on a `@Stateless` EJB —
   invalid; EJBs use `@javax.ejb.TransactionAttribute` instead. Liberty refused to start
   the app over it (`CWOWB2000E`).
2. `server.xml`'s `httpEndpoint` referenced `${liberty.var.default.http.port}`, but the
   `liberty.var.` prefix is a **pom.xml property-naming convention** for defining a
   Liberty variable, not part of the variable's actual name inside `server.xml` — it
   should reference `${default.http.port}`. Got this wrong initially; the endpoint just
   silently never bound to port 9080 with no error logged.
3. `OrderResource` (JAX-RS) had no CDI scope annotation. Under `beans.xml`'s
   `bean-discovery-mode="annotated"`, a class needs a CDI bean-defining annotation to be
   visible to CDI at all — without one, its `@EJB` field was never injected, so calling
   the endpoint threw a `NullPointerException`. Fixed by adding `@RequestScoped`.
4. `javax:javaee-api:8.0.1`'s POM does **not** actually declare a JAX-WS dependency,
   despite JAX-WS being part of the full EE8 platform. This was masked when compiling
   with an actual JDK 8 install, because JDK 8's own bundled runtime still ships
   `javax.jws`/`javax.xml.ws` (removed from the JDK entirely in Java 11+) — so the gap
   only surfaces as `package javax.jws does not exist` when compiling with JDK 11+.
   Fixed by adding explicit `javax.xml.ws:jaxws-api:2.3.1` (the JAX-WS API) **and**
   `javax.jws:javax.jws-api:1.1` (the separate `@WebService`/`@WebMethod` annotations
   artifact — these are two different jars) to `pom.xml`. **Compile with an actual JDK 8**
   regardless (e.g. `D:\Program Files\IBM\SDP\jdk` if you have IBM's), since
   `maven.compiler.source/target=1.8` only sets the bytecode version, not which JDK
   classes are available — this fix just stops the *build* from silently depending on
   JDK-bundled classes.

### Operational note: after `mvn clean`, redo the full Liberty sequence

`mvn clean` deletes `target/`, which includes the entire installed Liberty runtime under
`target/liberty/wlp` — including the downloaded `javaee-8.0` feature. Running
`mvn liberty:start` alone afterward will boot a bare kernel with **zero features
installed** (silently — it reports "started" even though nothing is listening). After a
clean, always run the full sequence:

```bash
mvn clean package
mvn liberty:create liberty:install-feature liberty:deploy
mvn liberty:start
```

`mvn liberty:dev` / `mvn liberty:run` handle this correctly on their own — this only
matters if you're scripting the `create`/`deploy`/`start` goals separately.

**JMS/MDB is intentionally not wired for the demo.** `OrderNotifierBean.java` and
`OrderQueueSender.java` are excluded from compilation (see `maven-compiler-plugin`
`<excludes>` in [pom.xml](pom.xml)) so a missing messaging-engine config can't block the
whole app from starting. The source stays in the tree — Discovery/Impact Analysis can
still find and assess it — it's just not part of the deployed WAR. If you want JMS live
for the demo instead, remove those two excludes and add a `wasJmsServer-1.0` /
`wasJmsClient-2.0` messaging engine + queue/activation-spec config to `server.xml`.

## Build info (Discovery-stage facts)

- JDK target: **8** (`maven.compiler.source/target = 1.8`)
- Build tool: Maven
- Packaging: WAR
- Aggregate API dependency: `javax:javaee-api:8.0.1` (provided)
- Target-server-specific descriptor present: `WEB-INF/glassfish-web.xml` (GlassFish/Payara family)

## Feature matrix

| Feature / JSR | javax package(s) used | File(s) | Jakarta EE 10 equivalent package |
|---|---|---|---|
| Servlet 4.0 | `javax.servlet.*` | [OrderExportServlet.java](src/main/java/com/acme/legacy/servlet/OrderExportServlet.java), [AppContextListener.java](src/main/java/com/acme/legacy/servlet/AppContextListener.java), [RequestLoggingFilter.java](src/main/java/com/acme/legacy/servlet/RequestLoggingFilter.java) | `jakarta.servlet.*` |
| JSP | (via `web.xml` welcome file) | [index.jsp](src/main/webapp/index.jsp) | n/a (JSP itself has no package, but the container API does) |
| JSF 2.3 (Facelets) | `javax.faces.*` | [OrderBackingBean.java](src/main/java/com/acme/legacy/jsf/OrderBackingBean.java), [orders.xhtml](src/main/webapp/orders.xhtml) | `jakarta.faces.*` |
| EJB 3.2 (Stateless/Singleton/MDB) | `javax.ejb.*` | [OrderProcessorBean.java](src/main/java/com/acme/legacy/ejb/OrderProcessorBean.java), [InventoryManagerBean.java](src/main/java/com/acme/legacy/ejb/InventoryManagerBean.java), [OrderNotifierBean.java](src/main/java/com/acme/legacy/ejb/OrderNotifierBean.java) | `jakarta.ejb.*` |
| JPA 2.2 | `javax.persistence.*` | [Customer.java](src/main/java/com/acme/legacy/entity/Customer.java), [Order.java](src/main/java/com/acme/legacy/entity/Order.java), [OrderItem.java](src/main/java/com/acme/legacy/entity/OrderItem.java), [persistence.xml](src/main/resources/META-INF/persistence.xml) | `jakarta.persistence.*` |
| CDI 2.0 (events, interceptors) | `javax.enterprise.*`, `javax.inject.*`, `javax.interceptor.*` | [OrderEventObserver.java](src/main/java/com/acme/legacy/cdi/OrderEventObserver.java), [AuditInterceptor.java](src/main/java/com/acme/legacy/cdi/AuditInterceptor.java), [beans.xml](src/main/webapp/WEB-INF/beans.xml) | `jakarta.enterprise.*`, `jakarta.inject.*`, `jakarta.interceptor.*` |
| Bean Validation 2.0 | `javax.validation.*` | [ValidSku.java](src/main/java/com/acme/legacy/validation/ValidSku.java), [SkuValidator.java](src/main/java/com/acme/legacy/validation/SkuValidator.java) | `jakarta.validation.*` |
| JAX-RS 2.1 | `javax.ws.rs.*` | [ApiApplication.java](src/main/java/com/acme/legacy/jaxrs/ApiApplication.java), [OrderResource.java](src/main/java/com/acme/legacy/jaxrs/OrderResource.java) | `jakarta.ws.rs.*` |
| JAX-WS 2.3 | `javax.jws.*` | [CustomerLookupService.java](src/main/java/com/acme/legacy/jaxws/CustomerLookupService.java) | `jakarta.jws.*` |
| JMS 2.0 *(source only — excluded from the build, see [Running it](#running-it-open-liberty))* | `javax.jms.*` | [OrderQueueSender.java](src/main/java/com/acme/legacy/jms/OrderQueueSender.java), [OrderNotifierBean.java](src/main/java/com/acme/legacy/ejb/OrderNotifierBean.java) | `jakarta.jms.*` |
| JSON-B 1.0 | `javax.json.bind.*` | [OrderJsonMapper.java](src/main/java/com/acme/legacy/json/OrderJsonMapper.java) | `jakarta.json.bind.*` |
| WebSocket 1.1 | `javax.websocket.*` | [OrderStatusEndpoint.java](src/main/java/com/acme/legacy/websocket/OrderStatusEndpoint.java) | `jakarta.websocket.*` |
| Concurrency Utilities 1.0 | `javax.enterprise.concurrent.*` | [AsyncReportGenerator.java](src/main/java/com/acme/legacy/concurrency/AsyncReportGenerator.java) | `jakarta.enterprise.concurrent.*` |
| Common Annotations 1.3 | `javax.annotation.*` | multiple (`@Resource`, `@PostConstruct`, `@Priority`) | `jakarta.annotation.*` |
| Java EE Security API 1.0 (JSR 375) | `javax.security.enterprise.*` | [AppIdentityStore.java](src/main/java/com/acme/legacy/security/AppIdentityStore.java) | `jakarta.security.enterprise.*` |
| JAXB 2.3 | `javax.xml.bind.*` | [CustomerXmlMapper.java](src/main/java/com/acme/legacy/xml/CustomerXmlMapper.java), `@XmlRootElement` on [Customer.java](src/main/java/com/acme/legacy/entity/Customer.java) | `jakarta.xml.bind.*` — **note:** also removed from the JDK itself starting at Java 11, independent of the Jakarta rename |

## Deliberate "trap" cases for the Impact Analysis stage

Not every `javax` reference is a Java import — these are included on purpose so the
impact-analysis tooling has to look past simple `import javax.*` regex matching:

1. **XML namespaces** in [web.xml](src/main/webapp/WEB-INF/web.xml), [persistence.xml](src/main/resources/META-INF/persistence.xml), [beans.xml](src/main/webapp/WEB-INF/beans.xml), [faces-config.xml](src/main/webapp/WEB-INF/faces-config.xml) all use the `http://xmlns.jcp.org/xml/ns/javaee` family of namespaces (Jakarta EE 9+ moves these to `https://jakarta.ee/xml/ns/jakartaee`).
2. **JSF Facelets taglib namespaces** in [orders.xhtml](src/main/webapp/orders.xhtml) (`http://xmlns.jcp.org/jsf/html`, `.../jsf/core`).
3. **String-literal `javax.*` values**, not imports:
   - `web.xml` context-param name `javax.faces.PROJECT_STAGE`
   - `persistence.xml` property key `javax.persistence.schema-generation.database.action`
   - `OrderNotifierBean`'s `@ActivationConfigProperty(propertyValue = "javax.jms.Queue")`
4. **Server-specific descriptor**: [glassfish-web.xml](src/main/webapp/WEB-INF/glassfish-web.xml) ties the app to the GlassFish/Payara runtime family — a "server dependency" Discovery should flag separately from the API-level analysis.
5. **Non-javax dependency contrast case**: [StringHelper.java](src/main/java/com/acme/legacy/util/StringHelper.java) uses `commons-lang3`, which needs no migration action at all — useful for confirming the impact analysis doesn't over-flag.
6. **JDK-removal vs. namespace-rename distinction**: JAXB (`javax.xml.bind.*`) is unusual in that it was both removed from the JDK (Java 11+) *and* renamed under Jakarta — two independent problems bundled in one dependency.

## What's intentionally NOT included

- Batch (JSR 352) and a few other minor EE8 specs, to keep the fixture readable.
- JMS/MDB is present as source but excluded from the compiled WAR (see above) — not wired up as a live feature in the demo.
- No test suite (out of scope for this fixture).
