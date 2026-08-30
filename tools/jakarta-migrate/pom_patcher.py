"""Reads dependency_map.json and applies Maven coordinate changes to a pom.xml file.

Only stdlib XML tooling is used (xml.etree.ElementTree) so there are no extra
dependencies beyond what Python ships with.

Maven POM namespace: http://maven.apache.org/POM/4.0.0
ElementTree requires every tag lookup to be namespace-qualified, e.g.:
    "{http://maven.apache.org/POM/4.0.0}dependency"

# VERIFY: namespace must be registered before serialisation or ElementTree will
# emit ugly ns0: prefixes — see patch_pom() for the register_namespace call.

Action types handled:
  replace       — swap groupId/artifactId/version/scope of an existing dep
  remove        — delete an existing dep element entirely
  add           — insert a new dep (no-op if target coord already present)
  version_bump  — update only the <version> of an existing dep
  (compiler)    — update <maven.compiler.source/target> in <properties> to 17
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

NS = "http://maven.apache.org/POM/4.0.0"
_NS = f"{{{NS}}}"   # shorthand for namespace-qualified tag, e.g. _NS + "dependency"

TARGET_JAVA_VERSION = "17"
# VERIFY: any compiler source/target value that is not already TARGET_JAVA_VERSION
# will be bumped.  This covers "1.8", "8", "11", "1.11", "16", etc.


@dataclass
class ChangeRecord:
    file: str            # path string, relative to repo root
    action: str          # "replace", "remove", "add", "version_bump", "compiler_bump"
    old_coordinate: str  # e.g. "javax:javaee-api:8.0.1"  or  "compiler:1.8"
    new_coordinate: str  # e.g. "jakarta.platform:jakarta.jakartaee-api:10.0.0"  or "compiler:17"
    map_key: str         # key used in dependency_map.json, or "compiler_source_target"


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def load_dependency_map(map_path: Path) -> dict:
    """Load and return the dependency_map.json as a plain dict.

    # VERIFY: caller is responsible for supplying a valid JSON file;
    # json.JSONDecodeError propagates up unchanged.
    """
    return json.loads(map_path.read_text(encoding="utf-8"))


def patch_pom(pom_path: Path, dep_map: dict) -> tuple[str, list[ChangeRecord]]:
    """Apply dep_map changes to the pom.xml at pom_path.

    Returns (patched_xml_str, changes) where:
      - patched_xml_str is the full updated XML (NOT written to disk)
      - changes is the list of ChangeRecord instances that were actually applied

    # VERIFY: non-matching dep_map keys are silently skipped (no ChangeRecord emitted).
    # VERIFY: the input file is never modified — only the returned string reflects changes.
    """
    # Register namespaces BEFORE parsing so ElementTree round-trips them cleanly.
    ET.register_namespace("", NS)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")

    tree = ET.parse(str(pom_path))
    root = tree.getroot()

    # Build a relative file path string for ChangeRecord.file
    # VERIFY: if pom_path is absolute we still emit a tidy relative string when possible.
    try:
        rel_file = str(pom_path.relative_to(Path.cwd()))
    except ValueError:
        rel_file = str(pom_path)

    changes: list[ChangeRecord] = []

    # Locate the single <dependencies> block.
    # VERIFY: only the top-level <dependencies> is targeted — not plugin <dependencies>.
    deps_elem = _find_top_level_dependencies(root)

    for map_key, entry in dep_map.items():
        action = entry.get("action", "")

        if action == "replace":
            _do_replace(root, deps_elem, map_key, entry, rel_file, changes)
        elif action == "remove":
            _do_remove(root, deps_elem, map_key, rel_file, changes)
        elif action == "add":
            _do_add(root, deps_elem, map_key, entry, rel_file, changes)
        elif action == "version_bump":
            _do_version_bump(root, deps_elem, map_key, entry, rel_file, changes)
        # VERIFY: unknown action values are silently ignored.

    # Compiler bump — always attempted after all dep entries.
    _do_compiler_bump(root, rel_file, changes)

    xml_str = _serialize(root)
    return xml_str, changes


# ---------------------------------------------------------------------------
# Internal helpers — element finders
# ---------------------------------------------------------------------------

def _find_top_level_dependencies(root: ET.Element) -> ET.Element | None:
    """Return the first <dependencies> that is a direct child of <project>.

    Maven build-plugin <dependencies> are nested deeper (inside <build><plugins>
    <plugin>) so restricting to a direct child avoids false matches.

    # VERIFY: returns None when the pom has no <dependencies> section at all.
    """
    return root.find(f"{_NS}dependencies")


def _find_dependency(deps_elem: ET.Element | None, group_id: str, artifact_id: str) -> ET.Element | None:
    """Find a <dependency> by groupId+artifactId within a <dependencies> element.

    # VERIFY: returns None (not an exception) when not found.
    """
    if deps_elem is None:
        return None
    for dep in deps_elem.findall(f"{_NS}dependency"):
        gid = dep.findtext(f"{_NS}groupId") or ""
        aid = dep.findtext(f"{_NS}artifactId") or ""
        if gid.strip() == group_id and aid.strip() == artifact_id:
            return dep
    return None


def _coord_from_dep(dep: ET.Element) -> str:
    """Build a "groupId:artifactId:version" string from a <dependency> element.

    # VERIFY: missing version element yields an empty string for that segment
    (e.g. "javax:javaee-api:").
    """
    gid = (dep.findtext(f"{_NS}groupId") or "").strip()
    aid = (dep.findtext(f"{_NS}artifactId") or "").strip()
    ver = (dep.findtext(f"{_NS}version") or "").strip()
    return f"{gid}:{aid}:{ver}"


def _parse_map_key(map_key: str) -> tuple[str, str]:
    """Split a 'groupId:artifactId' map key into its two parts.

    # VERIFY: keys are always exactly two colon-separated segments in dependency_map.json.
    # If the key somehow has more segments (e.g. a GAV triple), only the first two are used.
    """
    parts = map_key.split(":", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


# ---------------------------------------------------------------------------
# Internal helpers — action implementations
# ---------------------------------------------------------------------------

def _do_replace(
    root: ET.Element,
    deps_elem: ET.Element | None,
    map_key: str,
    entry: dict,
    rel_file: str,
    changes: list[ChangeRecord],
) -> None:
    """Replace groupId/artifactId/version/scope on an existing <dependency>.

    # VERIFY: if the dep is not found in the pom, no ChangeRecord is emitted.
    # VERIFY: <version> is added if missing; <scope> is added only when the
    # target scope is not "compile".
    """
    src_gid, src_aid = _parse_map_key(map_key)
    dep = _find_dependency(deps_elem, src_gid, src_aid)
    if dep is None:
        return  # VERIFY: silently skip missing deps

    old_coord = _coord_from_dep(dep)

    tgt_gid = entry.get("targetGroupId", src_gid)
    tgt_aid = entry.get("targetArtifactId", src_aid)
    tgt_ver = entry.get("targetVersion", "")
    tgt_scope = entry.get("scope", "compile")

    _set_text(dep, f"{_NS}groupId", tgt_gid)
    _set_text(dep, f"{_NS}artifactId", tgt_aid)
    _set_or_add_child(dep, f"{_NS}version", tgt_ver)

    scope_elem = dep.find(f"{_NS}scope")
    if scope_elem is not None:
        scope_elem.text = tgt_scope
    elif tgt_scope != "compile":
        # VERIFY: only add <scope> when it's not the default "compile" scope,
        # mirroring Maven's convention of omitting scope for compile-scoped deps.
        _append_child_with_indent(dep, f"{_NS}scope", tgt_scope)

    new_coord = f"{tgt_gid}:{tgt_aid}:{tgt_ver}"
    changes.append(ChangeRecord(
        file=rel_file,
        action="replace",
        old_coordinate=old_coord,
        new_coordinate=new_coord,
        map_key=map_key,
    ))


def _do_remove(
    root: ET.Element,
    deps_elem: ET.Element | None,
    map_key: str,
    rel_file: str,
    changes: list[ChangeRecord],
) -> None:
    """Remove a <dependency> element from <dependencies>.

    Also cleans up the leading whitespace/newline so indentation stays tidy.

    # VERIFY: if the dep is not found, no ChangeRecord is emitted and no error is raised.
    """
    src_gid, src_aid = _parse_map_key(map_key)
    dep = _find_dependency(deps_elem, src_gid, src_aid)
    if dep is None:
        return  # VERIFY: silently skip

    old_coord = _coord_from_dep(dep)

    # Clean up the whitespace/newline before this element.
    # ElementTree stores inter-element whitespace as .tail on the preceding sibling
    # (or .text on the parent if it's the first child).
    _remove_preceding_whitespace(deps_elem, dep)
    deps_elem.remove(dep)

    changes.append(ChangeRecord(
        file=rel_file,
        action="remove",
        old_coordinate=old_coord,
        new_coordinate="",
        map_key=map_key,
    ))


def _do_add(
    root: ET.Element,
    deps_elem: ET.Element | None,
    map_key: str,
    entry: dict,
    rel_file: str,
    changes: list[ChangeRecord],
) -> None:
    """Append a new <dependency> after the last existing one.

    # VERIFY: if the target groupId:artifactId already exists in the pom, this
    # is a no-op and no ChangeRecord is emitted.
    # VERIFY: if <dependencies> is missing from the pom, the add is skipped.
    """
    if deps_elem is None:
        return

    tgt_gid = entry.get("targetGroupId", "")
    tgt_aid = entry.get("targetArtifactId", "")
    tgt_ver = entry.get("targetVersion", "")
    tgt_scope = entry.get("scope", "compile")

    # Guard: skip if target coordinate already present.
    # VERIFY: check is against the TARGET coord, not the source map key coord.
    existing = _find_dependency(deps_elem, tgt_gid, tgt_aid)
    if existing is not None:
        return  # VERIFY: already present — skip silently, no ChangeRecord

    # Detect indentation from the last existing <dependency> element so the new
    # element aligns with its siblings.
    # VERIFY: falls back to 8-space indent (common Maven style) when no siblings exist.
    indent = _detect_dep_indent(deps_elem)

    inner = indent + "    "  # one extra level of indent for child elements

    new_dep = ET.Element(f"{_NS}dependency")
    new_dep.text = f"\n{inner}"        # indent before first child element
    new_dep.tail = f"\n{indent}"       # spacing after </dependency>, same level as siblings

    _append_child_inline(new_dep, f"{_NS}groupId", tgt_gid, inner)
    _append_child_inline(new_dep, f"{_NS}artifactId", tgt_aid, inner)
    _append_child_inline(new_dep, f"{_NS}version", tgt_ver, inner)
    if tgt_scope != "compile":
        # VERIFY: omit <scope> for compile-scoped deps (Maven default).
        _append_child_inline(new_dep, f"{_NS}scope", tgt_scope, inner)

    # Fix the last child's tail to align </dependency> with siblings.
    # VERIFY: the last child's tail must end at the dep-level indent, not the inner
    # indent — otherwise the closing </dependency> tag is indented too far.
    last_child = list(new_dep)[-1]
    last_child.tail = f"\n{indent}"

    # Fix up the last child's tail so the new <dependency> starts on its own line.
    all_deps = deps_elem.findall(f"{_NS}dependency")
    if all_deps:
        last_dep = all_deps[-1]
        # VERIFY: override the last dep's tail to include a blank separator line,
        # matching the style used in javaee8-order-management/pom.xml.
        last_dep.tail = f"\n\n{indent}"
    else:
        # No existing deps — set parent text so first child is indented.
        deps_elem.text = f"\n{indent}"

    deps_elem.append(new_dep)

    new_coord = f"{tgt_gid}:{tgt_aid}:{tgt_ver}"
    changes.append(ChangeRecord(
        file=rel_file,
        action="add",
        old_coordinate="",
        new_coordinate=new_coord,
        map_key=map_key,
    ))


def _do_version_bump(
    root: ET.Element,
    deps_elem: ET.Element | None,
    map_key: str,
    entry: dict,
    rel_file: str,
    changes: list[ChangeRecord],
) -> None:
    """Update only the <version> text of an existing <dependency>.

    # VERIFY: if the dep is not found, no ChangeRecord is emitted.
    # VERIFY: <version> is added if missing (same as replace).
    """
    src_gid, src_aid = _parse_map_key(map_key)
    dep = _find_dependency(deps_elem, src_gid, src_aid)
    if dep is None:
        return  # VERIFY: silently skip missing deps

    old_coord = _coord_from_dep(dep)
    tgt_ver = entry.get("targetVersion", "")

    _set_or_add_child(dep, f"{_NS}version", tgt_ver)

    new_coord = f"{src_gid}:{src_aid}:{tgt_ver}"
    changes.append(ChangeRecord(
        file=rel_file,
        action="version_bump",
        old_coordinate=old_coord,
        new_coordinate=new_coord,
        map_key=map_key,
    ))


def _do_compiler_bump(
    root: ET.Element,
    rel_file: str,
    changes: list[ChangeRecord],
) -> None:
    """Bump <maven.compiler.source> and <maven.compiler.target> to TARGET_JAVA_VERSION.

    A bump is recorded only when at least one of the two properties is found AND
    its value is not already TARGET_JAVA_VERSION.

    # VERIFY: if neither property exists in the pom, no ChangeRecord is emitted.
    # VERIFY: only one ChangeRecord is emitted even when both properties are updated.
    # VERIFY: values such as "1.8", "8", "11", "1.11", "16" are all treated as
    # "needs bumping" — the check is simply "!= TARGET_JAVA_VERSION".
    """
    props = root.find(f"{_NS}properties")
    if props is None:
        return

    source_elem = props.find(f"{_NS}maven.compiler.source")
    target_elem = props.find(f"{_NS}maven.compiler.target")

    old_source = (source_elem.text or "").strip() if source_elem is not None else None
    old_target = (target_elem.text or "").strip() if target_elem is not None else None

    # Nothing to do if neither property is present.
    if old_source is None and old_target is None:
        return

    # Already at target version — nothing to bump.
    already_ok = (
        (old_source is None or old_source == TARGET_JAVA_VERSION)
        and (old_target is None or old_target == TARGET_JAVA_VERSION)
    )
    if already_ok:
        return

    old_val = old_source or old_target or ""

    if source_elem is not None:
        source_elem.text = TARGET_JAVA_VERSION
    if target_elem is not None:
        target_elem.text = TARGET_JAVA_VERSION

    changes.append(ChangeRecord(
        file=rel_file,
        action="compiler_bump",
        old_coordinate=f"compiler:{old_val}",
        new_coordinate=f"compiler:{TARGET_JAVA_VERSION}",
        map_key="compiler_source_target",
    ))


# ---------------------------------------------------------------------------
# Internal helpers — element manipulation
# ---------------------------------------------------------------------------

def _set_text(parent: ET.Element, tag: str, text: str) -> None:
    """Set the text of an existing child element; no-op if the child is missing.

    # VERIFY: does NOT create the element — use _set_or_add_child for that.
    """
    elem = parent.find(tag)
    if elem is not None:
        elem.text = text


def _set_or_add_child(parent: ET.Element, tag: str, text: str) -> None:
    """Set the text of an existing child element, or append it if absent.

    # VERIFY: when the element is appended it inherits the same tail indentation
    # as the last existing child so formatting stays consistent.
    """
    elem = parent.find(tag)
    if elem is not None:
        elem.text = text
    else:
        _append_child_with_indent(parent, tag, text)


def _append_child_with_indent(parent: ET.Element, tag: str, text: str) -> None:
    """Create a new child element at the end of parent, preserving indentation.

    Copies the tail of the last existing child (which encodes the newline +
    indent that precedes the next sibling) so the new element aligns correctly.

    # VERIFY: if parent has no children, falls back to 8-space indent.
    """
    children = list(parent)
    if children:
        ref_tail = children[-1].tail or ""
    else:
        ref_tail = "\n        "  # fallback: 8-space Maven indent

    new_elem = ET.SubElement(parent, tag)
    new_elem.text = text
    new_elem.tail = ref_tail  # same indentation as siblings


def _append_child_inline(parent: ET.Element, tag: str, text: str, indent: str | None = None) -> None:
    """Append a child element with inline formatting (used inside a new <dependency>).

    Sets .tail to a newline + consistent indent so children stack vertically.
    Subsequent children are added with the same pattern.

    When indent is provided explicitly it is used directly; otherwise it is
    detected from parent.text via _detect_inner_indent.

    # VERIFY: the parent's .text already contains the opening newline+indent;
    # this function only handles the element's own tail.
    """
    if indent is None:
        indent = _detect_inner_indent(parent)
    new_elem = ET.SubElement(parent, tag)
    new_elem.text = text
    new_elem.tail = f"\n{indent}"


def _detect_dep_indent(deps_elem: ET.Element) -> str:
    """Detect the indentation string used for <dependency> children of deps_elem.

    Inspects the .tail of the first <dependency> child to extract the leading
    whitespace on the line that follows it.

    # VERIFY: falls back to 8 spaces (typical Maven 4-space-indent project with
    # <project>→<dependencies>→<dependency> nesting) when detection fails.
    """
    dep_children = deps_elem.findall(f"{_NS}dependency")
    if dep_children:
        # tail of a dep is the whitespace AFTER its closing tag; it ends with
        # the indent that precedes the NEXT sibling — that's the indent level we want.
        tail = dep_children[0].tail or ""
        # Extract the trailing whitespace (spaces/tabs) after the last newline.
        m = re.search(r"\n([ \t]*)$", tail)
        if m:
            return m.group(1)
    return "        "  # 8-space fallback


def _detect_inner_indent(dep_elem: ET.Element) -> str:
    """Detect the indent used inside a <dependency> element.

    Reads dep_elem.text which contains the newline+indent before the first child.

    # VERIFY: falls back to 12 spaces (8 outer + 4 inner) when not detectable.
    """
    text = dep_elem.text or ""
    m = re.search(r"\n([ \t]*)$", text)
    if m:
        return m.group(1)
    return "            "  # 12-space fallback


def _remove_preceding_whitespace(parent: ET.Element, child: ET.Element) -> None:
    """Remove leading whitespace that precedes child within parent.

    ElementTree stores inter-element text in two places:
      - parent.text: whitespace before the *first* child
      - sibling.tail: whitespace after a sibling and before the next element

    After removing child, its own tail (whitespace after it) would shift to the
    preceding sibling's tail.  Instead we strip the tail of the preceding sibling
    so the surrounding elements close the gap cleanly.

    # VERIFY: when child is the first (or only) element, parent.text is trimmed
    # to remove the extra blank line that would otherwise remain.
    """
    children = list(parent)
    idx = children.index(child)

    if idx == 0:
        # child is the first element — strip leading whitespace from parent.text.
        parent.text = (parent.text or "").rstrip(" \t")
        # If there's a following sibling, its indentation is already correct.
    else:
        prev = children[idx - 1]
        # Drop the blank lines in the prev sibling's tail that were "shared" with
        # the element being removed; keep only a single newline+indent.
        tail = prev.tail or ""
        # Collapse multiple blank lines down to one newline + the indent level.
        indent = _detect_dep_indent(parent)
        prev.tail = f"\n\n        {indent.lstrip()}" if "\n\n" in tail else f"\n{indent}"


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _serialize(root: ET.Element) -> str:
    """Serialise the ElementTree root to a UTF-8 XML string with declaration.

    # VERIFY: ET.tostring with encoding="unicode" returns a str (not bytes) and
    # does NOT emit a byte-order mark.  The xml_declaration=True kwarg was added
    # in Python 3.8; on older versions a manual header must be prepended.
    """
    # xml_declaration=True requires encoding != "unicode" in Python's ET, so we
    # manually prepend the declaration instead.
    body = ET.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}'
