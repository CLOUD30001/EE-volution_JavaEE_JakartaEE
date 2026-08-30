"""Reads feature_map.json and updates Liberty <featureManager> entries in server.xml.

Liberty server.xml has NO default XML namespace — tag names are unqualified,
so no namespace prefix is required when searching with ElementTree.

Only stdlib XML tooling is used (xml.etree.ElementTree).

Action types emitted:
  replace   — feature name found in feature_map; text updated to mapped value
  no_rule   — feature name not present in feature_map; element left unchanged
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from pom_patcher import ChangeRecord


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def patch_server_xml(
    server_xml_path: Path,
    feature_map: dict,
) -> tuple[str, list[ChangeRecord]]:
    """Apply feature_map renames to the Liberty server.xml at server_xml_path.

    Returns (patched_xml_str, changes).

    * If <featureManager> is absent, returns (original_xml_string, []) unchanged.
    * Does NOT write to disk — the caller is responsible for persisting the result.
    """
    original = server_xml_path.read_text(encoding="utf-8")

    root = ET.fromstring(original)

    feature_manager = root.find("featureManager")
    if feature_manager is None:
        return original, []

    changes: list[ChangeRecord] = []

    for feature_elem in feature_manager.findall("feature"):
        feature_text = feature_elem.text or ""

        if feature_text in feature_map:
            new_name = feature_map[feature_text]
            changes.append(
                ChangeRecord(
                    file=str(server_xml_path),
                    action="replace",
                    old_coordinate=feature_text,
                    new_coordinate=new_name,
                    map_key=feature_text,
                )
            )
            feature_elem.text = new_name
        else:
            changes.append(
                ChangeRecord(
                    file=str(server_xml_path),
                    action="no_rule",
                    old_coordinate=feature_text,
                    new_coordinate=feature_text,
                    map_key="",
                )
            )

    patched = ET.tostring(root, encoding="unicode")
    return patched, changes
