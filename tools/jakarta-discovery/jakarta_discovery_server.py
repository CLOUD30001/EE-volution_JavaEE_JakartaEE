import fnmatch
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterator

from fastmcp import FastMCP

mcp = FastMCP("jakarta-discovery-server")

# ---------------------------------------------------------------------------
# Shared data / helpers
# ---------------------------------------------------------------------------

# Directories to skip in every scan: build output, downloaded server runtimes
# (e.g. `mvn liberty:dev` populates target/liberty/wlp with an entire Liberty
# install), VCS metadata, IDE state.
EXCLUDED_DIR_NAMES = {
    "target", "build", ".git", "node_modules", ".gradle",
    ".idea", ".vscode", "out", "bin",
}


def _iter_files(root_dir: Path, pattern: str) -> Iterator[Path]:
    """Walks root_dir yielding files matching a glob pattern, pruning excluded
    directories *before* descending into them."""
    for dirpath, dirnames, filenames in os.walk(root_dir, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIR_NAMES]
        for filename in fnmatch.filter(filenames, pattern):
            yield Path(dirpath) / filename


# Java SE APIs that must stay javax.* — governed by the JDK, not Jakarta EE.
JAVA_SE_EXCLUSIONS = {
    "javax.sql", "javax.naming", "javax.management", "javax.crypto",
    "javax.net", "javax.xml.parsers", "javax.xml.transform", "javax.xml.namespace",
    "javax.xml.xpath", "javax.xml.datatype", "javax.script", "javax.swing",
    "javax.smartcardio", "javax.security.auth", "javax.security.sasl",
    "javax.tools", "javax.print", "javax.sound", "javax.imageio", "javax.accessibility",
}

# Complete 16-spec-family mapping (Migration Blueprint v3).
SPEC_MAPPING = {
    "javax.servlet.jsp": "Jakarta Pages 3.1",
    "javax.servlet": "Jakarta Servlet 6.0",
    "javax.faces": "Jakarta Faces 4.0",
    "javax.ejb": "Jakarta Enterprise Beans 4.0",
    "javax.persistence": "Jakarta Persistence 3.1",
    "javax.enterprise.concurrent": "Jakarta Concurrency 3.0",
    "javax.enterprise": "Jakarta CDI 4.0",
    "javax.inject": "Jakarta CDI 4.0",
    "javax.interceptor": "Jakarta CDI 4.0",
    "javax.validation": "Jakarta Bean Validation 3.0",
    "javax.ws.rs": "Jakarta REST 3.1",
    "javax.jws": "Jakarta XML Web Services 4.0 (High Risk)",
    "javax.xml.ws": "Jakarta XML Web Services 4.0 (High Risk)",
    "javax.jms": "Jakarta Messaging 3.1",
    "javax.json.bind": "Jakarta JSON Binding 3.0",
    "javax.websocket": "Jakarta WebSocket 2.1",
    "javax.annotation": "Jakarta Annotations 2.1 (Needs Explicit Dep)",
    "javax.security.enterprise": "Jakarta Security 3.0",
    "javax.xml.bind": "Jakarta XML Binding 4.0 (JAXB - JDK11+ Removal Risk)",
}

# Longest-prefix-first
SORTED_SPEC_PREFIXES = sorted(SPEC_MAPPING.items(), key=lambda item: len(item[0]), reverse=True)


def _classify_spec(pkg: str) -> str:
    for prefix, spec_name in SORTED_SPEC_PREFIXES:
        if pkg.startswith(prefix):
            return spec_name
    return "Other Jakarta Spec"


# ---------------------------------------------------------------------------
# Tool 1: scan_javax_usage
# ---------------------------------------------------------------------------

IMPORT_PATTERN = re.compile(
    r"^\s*import\s+(?:static\s+)?(javax\.[A-Za-z0-9_.]+(?:\.\*)?)\s*;"
)


@mcp.tool()
def scan_javax_usage(repo_path: str) -> Dict[str, Any]:
    """Scans .java source files and maps legacy javax imports
    across all 16 Jakarta EE spec families, excluding Java SE APIs."""
    root_dir = Path(repo_path)
    if not root_dir.exists():
        return {"error": f"Path '{repo_path}' does not exist."}

    results: Dict[str, Any] = {
        "total_files_scanned": 0,
        "files_with_javax": 0,
        "spec_family_counts": {},
        "file_details": {},
        "skipped": [],
    }

    for java_file in _iter_files(root_dir, "*.java"):
        results["total_files_scanned"] += 1
        file_imports = []

        try:
            with open(java_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    match = IMPORT_PATTERN.match(line)
                    if not match:
                        continue
                    pkg = match.group(1)
                    if any(pkg.startswith(ex) for ex in JAVA_SE_EXCLUSIONS):
                        continue
                    file_imports.append(pkg)
                    spec_matched = _classify_spec(pkg)
                    results["spec_family_counts"][spec_matched] = (
                        results["spec_family_counts"].get(spec_matched, 0) + 1
                    )
        except OSError as exc:
            results["skipped"].append({
                "file": str(java_file.relative_to(root_dir)),
                "reason": str(exc),
            })
            continue

        if file_imports:
            results["files_with_javax"] += 1
            results["file_details"][str(java_file.relative_to(root_dir))] = file_imports

    return results


# ---------------------------------------------------------------------------
# Tool 2: descriptor_audit
# ---------------------------------------------------------------------------

KNOWN_DESCRIPTOR_NAMES = {
    "web.xml", "persistence.xml", "beans.xml", "ejb-jar.xml",
    "faces-config.xml", "application.xml", "webservices.xml",
}
VENDOR_DESCRIPTOR_MARKERS = ("glassfish", "weblogic", "jboss", "ibm-web", "sun-web")

FACELETS_NS_PATTERN = re.compile(r'xmlns:([\w-]+)\s*=\s*"([^"]+)"')
LIBERTY_FEATURE_PATTERN = re.compile(r"<feature>\s*([^<\s]+)\s*</feature>")


def _classify_liberty_feature(feature: str) -> str:
    f = feature.strip().lower()
    if re.match(r"^javaee-\d", f):
        return "legacy"
    if re.match(r"^jakartaee-\d", f):
        return "current"
    return "unclassified"


def _is_legacy_namespace(ns: str) -> bool:
    ns_lower = ns.lower()
    return "javaee" in ns_lower or "jcp.org" in ns_lower or "sun.com" in ns_lower


def _is_relevant_descriptor(path: Path) -> bool:
    name = path.name.lower()
    if name in KNOWN_DESCRIPTOR_NAMES:
        return True
    if name == "server.xml":
        return True
    if "taglib" in name:
        return True
    return any(marker in name for marker in VENDOR_DESCRIPTOR_MARKERS)


def _all_audit_files(root_dir: Path) -> Iterator[Path]:
    yield from _iter_files(root_dir, "*.xml")
    yield from _iter_files(root_dir, "*.xhtml")


def _audit_facelets(xhtml_file: Path, rel_path: str, skipped: list) -> Dict[str, Any] | None:
    try:
        text = xhtml_file.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        skipped.append({"file": rel_path, "reason": str(exc)})
        return None

    ns_declarations = FACELETS_NS_PATTERN.findall(text)
    legacy_ns = {prefix: uri for prefix, uri in ns_declarations if _is_legacy_namespace(uri)}
    return {
        "file": rel_path,
        "descriptor_type": "Facelets View",
        "namespaces_declared": dict(ns_declarations),
        "legacy_namespaces": legacy_ns,
        "needs_migration": bool(legacy_ns),
        "risk_category": "Facelets Taglib Namespace" if legacy_ns else "Up-to-date",
    }


def _audit_liberty_server(server_xml: Path, rel_path: str, skipped: list) -> Dict[str, Any] | None:
    try:
        text = server_xml.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        skipped.append({"file": rel_path, "reason": str(exc)})
        return None

    features = LIBERTY_FEATURE_PATTERN.findall(text)
    legacy_features = [f for f in features if _classify_liberty_feature(f) == "legacy"]
    unclassified_features = [f for f in features if _classify_liberty_feature(f) == "unclassified"]

    if legacy_features:
        needs_migration = True
    elif not features or unclassified_features:
        needs_migration = None
    else:
        needs_migration = False

    return {
        "file": rel_path,
        "descriptor_type": "Liberty Server Config",
        "features_declared": features,
        "legacy_features": legacy_features,
        "unclassified_features": unclassified_features,
        "needs_migration": needs_migration,
        "risk_category": "Vendor Runtime Lock-in",
    }


def _audit_vendor_descriptor(vendor_file: Path, rel_path: str, skipped: list) -> Dict[str, Any] | None:
    try:
        ET.parse(vendor_file)
    except (ET.ParseError, OSError) as exc:
        skipped.append({"file": rel_path, "reason": str(exc)})
        return None

    return {
        "file": rel_path,
        "descriptor_type": "Vendor/Server Specific",
        "needs_migration": None,
        "requires_manual_review": True,
        "risk_category": "Vendor Runtime Lock-in",
        "note": "No automated content check exists for this descriptor type — audit manually once the target runtime is chosen.",
    }


def _audit_xml_descriptor(xml_file: Path, rel_path: str, skipped: list) -> Dict[str, Any] | None:
    try:
        tree = ET.parse(xml_file)
    except (ET.ParseError, OSError) as exc:
        skipped.append({"file": rel_path, "reason": str(exc)})
        return None

    root = tree.getroot()
    ns = root.tag.split("}")[0].strip("{") if "}" in root.tag else ""
    schema_loc = root.attrib.get("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation", "")
    version = root.attrib.get("version", "Unknown")
    filename = xml_file.name.lower()

    if filename == "persistence.xml":
        is_valid_jakarta = "https://jakarta.ee/xml/ns/persistence" in ns and version == "3.1"
    else:
        is_valid_jakarta = "https://jakarta.ee/xml/ns/jakartaee" in ns

    return {
        "file": rel_path,
        "descriptor_type": xml_file.name,
        "version": version,
        "namespace": ns,
        "schema_location": schema_loc,
        "needs_migration": not is_valid_jakarta,
        "risk_category": "Schema Namespace Update" if not is_valid_jakarta else "Up-to-date",
    }


@mcp.tool()
def descriptor_audit(repo_path: str) -> Dict[str, Any]:
    """Audits EE deployment descriptors, vendor/server descriptors, and JSF Facelets
    taglib namespaces declared inside .xhtml files."""
    root_dir = Path(repo_path)
    if not root_dir.exists():
        return {"error": f"Path '{repo_path}' does not exist."}

    audit_results = []
    skipped: list = []

    for audit_file in _all_audit_files(root_dir):
        rel_path = str(audit_file.relative_to(root_dir))
        filename = audit_file.name.lower()

        if audit_file.suffix == ".xhtml":
            entry = _audit_facelets(audit_file, rel_path, skipped)
        elif filename == "server.xml":
            entry = _audit_liberty_server(audit_file, rel_path, skipped)
        elif any(marker in filename for marker in VENDOR_DESCRIPTOR_MARKERS):
            entry = _audit_vendor_descriptor(audit_file, rel_path, skipped)
        elif _is_relevant_descriptor(audit_file):
            entry = _audit_xml_descriptor(audit_file, rel_path, skipped)
        else:
            continue

        if entry is not None:
            audit_results.append(entry)

    return {"descriptors_found": len(audit_results), "details": audit_results, "skipped": skipped}


# ---------------------------------------------------------------------------
# Tool 3: scan_config_literals
# ---------------------------------------------------------------------------

_SPEC_SUFFIXES = sorted(
    (re.escape(prefix[len("javax."):]) for prefix in SPEC_MAPPING),
    key=len,
    reverse=True,
)
CONFIG_LITERAL_PATTERN = re.compile(
    r"\bjavax\.(?:" + "|".join(_SPEC_SUFFIXES) + r")(?:\.[A-Za-z0-9_\-]+)*"
)


@mcp.tool()
def scan_config_literals(repo_path: str) -> Dict[str, Any]:
    """Scans files for javax.* string/config literals."""
    root_dir = Path(repo_path)
    if not root_dir.exists():
        return {"error": f"Path '{repo_path}' does not exist."}

    matches = []
    skipped = []
    file_patterns = ["*.java", "*.properties", "*.xml", "*.yaml", "*.yml"]

    for pattern in file_patterns:
        for filepath in _iter_files(root_dir, pattern):
            rel_path = str(filepath.relative_to(root_dir))
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, start=1):
                        stripped = line.strip()
                        if stripped.startswith("import "):
                            continue
                        for literal in CONFIG_LITERAL_PATTERN.findall(line):
                            matches.append({
                                "file": rel_path,
                                "line_number": line_num,
                                "matched_literal": literal,
                                "spec_family": _classify_spec(literal),
                                "snippet": stripped,
                            })
            except OSError as exc:
                skipped.append({"file": rel_path, "reason": str(exc)})
                continue

    return {"literal_count": len(matches), "details": matches, "skipped": skipped}


# ---------------------------------------------------------------------------
# Tool 4: parse_dependency_tree
# ---------------------------------------------------------------------------

LEGACY_DEP_MARKERS = ("javax", "javaee", "jettison", "jaxb")


def _is_legacy_dependency(group_id: str, artifact_id: str) -> bool:
    return any(m in group_id or m in artifact_id for m in LEGACY_DEP_MARKERS)


def _parse_maven(pom: Path, root_dir: Path, skipped: list) -> list:
    """Parse one pom.xml and return a list of Maven dependency dicts."""
    maven_ns = "{http://maven.apache.org/POM/4.0.0}"
    rel_path = str(pom.relative_to(root_dir))
    try:
        tree = ET.parse(pom)
    except (ET.ParseError, OSError) as exc:
        skipped.append({"file": rel_path, "reason": str(exc)})
        return []

    root = tree.getroot()
    ns = maven_ns if root.tag.startswith(maven_ns) else ""
    
    return [
        {
            "build_system": "Maven",
            "source_file": rel_path,
            "groupId": (g := dep.findtext(f"{ns}groupId", "")),
            "artifactId": (a := dep.findtext(f"{ns}artifactId", "")),
            "version": dep.findtext(f"{ns}version", "Managed/Inherited"),
            "scope": dep.findtext(f"{ns}scope", "compile"),
            "looks_legacy": _is_legacy_dependency(g, a),
        }
        for dep in root.findall(f".//{ns}dependencies/{ns}dependency")
    ]


@mcp.tool()
def parse_dependency_tree(repo_path: str) -> Dict[str, Any]:
    """Inventories dependencies for Maven (pom.xml). Returns every dependency
    found — deciding which ones need a jakarta-compatible bump is Impact Analysis's 
    job, not Discovery's. Each entry carries a `looks_legacy` hint only."""
    root_dir = Path(repo_path)
    if not root_dir.exists():
        return {"error": f"Path '{repo_path}' does not exist."}

    manifests: Dict[str, Any] = {
        "build_systems_detected": [],
        "maven_poms": [],
        "dependencies": [],
        "skipped": [],
    }

    poms = list(_iter_files(root_dir, "pom.xml"))

    if poms:
        manifests["build_systems_detected"].append("Maven")

    # --- Maven ---
    for pom in poms:
        manifests["maven_poms"].append(str(pom.relative_to(root_dir)))
        manifests["dependencies"].extend(
            _parse_maven(pom, root_dir, manifests["skipped"])
        )

    return manifests


if __name__ == "__main__":
    mcp.run()