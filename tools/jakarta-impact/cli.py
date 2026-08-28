"""python -m jakarta_impact --repo <path> --discovery <discovery-report.json> [options]

Produces impact-facts.json - Layer A's raw output for the Impact Analysis stage.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from report_builder import build_impact_facts, write_impact_facts


def _read_json_file(path: Path) -> dict:
    """Read a JSON file and return its contents as a dict.

    Returns an empty dict if the file is absent or unparseable.
    """
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _resolve_editor_settings() -> tuple[str | None, str | None]:
    """Resolve java_home and mvn_cmd from the Bob / VS Code editor global settings.

    Looks for settings in (first match wins per value):
      - ~/.bob/settings/settings.json   (Bob IDE)
      - %APPDATA%/Code - Insiders/User/settings.json
      - %APPDATA%/Code/User/settings.json          (VS Code stable)
      - ~/Library/Application Support/Code/User/settings.json  (macOS)
      - ~/.config/Code/User/settings.json           (Linux)

    Keys read:
      java_home  ← ``java.configuration.runtimes`` array entry where
                   ``"default": true`` (or the first entry), field ``"path"``
      mvn_cmd    ← ``maven.executable.path``
    """
    import os

    candidates: list[Path] = [
        Path.home() / ".bob" / "settings" / "settings.json",
    ]

    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates += [
            Path(appdata) / "Code - Insiders" / "User" / "settings.json",
            Path(appdata) / "Code" / "User" / "settings.json",
        ]

    candidates += [
        # macOS
        Path.home() / "Library" / "Application Support" / "Code" / "User" / "settings.json",
        # Linux
        Path.home() / ".config" / "Code" / "User" / "settings.json",
    ]

    java_home: str | None = None
    mvn_cmd: str | None = None

    for settings_path in candidates:
        if java_home and mvn_cmd:
            break
        cfg = _read_json_file(settings_path)
        if not cfg:
            continue

        if not java_home:
            runtimes = cfg.get("java.configuration.runtimes")
            if isinstance(runtimes, list) and runtimes:
                # Prefer the entry marked default=true, otherwise take the first.
                entry = next(
                    (r for r in runtimes if isinstance(r, dict) and r.get("default")),
                    runtimes[0],
                )
                java_home = entry.get("path") if isinstance(entry, dict) else None

        if not mvn_cmd:
            mvn_cmd = cfg.get("maven.executable.path") or None

    return java_home, mvn_cmd


def main(argv: list[str] | None = None) -> int:
    editor_java_home, editor_mvn_cmd = _resolve_editor_settings()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path, help="Path to the target Maven project (must already be `mvn package`-built)")
    parser.add_argument("--discovery", required=True, type=Path, help="Path to Stage 1's discovery-report.json")
    parser.add_argument("--java-home", default=None, help="JDK 11+ home used to run Eclipse Transformer (overrides editor setting 'java.configuration.runtimes')")
    parser.add_argument("--work-dir", type=Path, default=None, help="Scratch dir for resolved jars, transformed WAR, and logs (default: <repo>/target/jakarta-impact)")
    parser.add_argument("--mvn", default=None, help="Maven executable (overrides editor setting 'maven.executable.path'; default: mvn on PATH)")
    parser.add_argument("--out", type=Path, default=None, help="Output path (default: alongside --discovery, as impact-facts.json)")
    args = parser.parse_args(argv)

    # Resolve java-home: editor global settings first, then --java-home CLI arg.
    java_home: str | None = editor_java_home or args.java_home
    if not java_home:
        parser.error(
            "--java-home is required when 'java.configuration.runtimes' is not "
            "configured in the editor global settings "
            "(~/.bob/settings/settings.json or VS Code User settings.json)"
        )

    # Resolve mvn: editor global settings first, then --mvn CLI arg, then default.
    mvn_cmd: str = editor_mvn_cmd or args.mvn or "mvn"

    work_dir = args.work_dir or (args.repo / "target" / "jakarta-impact")
    # Default beside --discovery, not under the target project's own tree - pipeline
    # output shouldn't live inside the app being analyzed (see reports/ at the repo root).
    out_path = args.out or (args.discovery.parent / "impact-facts.json")

    facts = build_impact_facts(
        repo_path=args.repo,
        discovery_report_path=args.discovery,
        java_home=java_home,
        work_dir=work_dir,
        mvn_cmd=mvn_cmd,
    )
    write_impact_facts(facts, out_path)

    sc = facts["sourceCoverage"]
    print(f"Wrote {out_path}")
    print(f"Source files with javax usage: {sc['totalFilesWithJavax']}")
    print(f"  mechanically covered:     {sc['mechanicallyCovered']}")
    print(f"  NOT mechanically covered: {sc['notMechanicallyCovered']}")
    print(f"Judgment-call candidates: {len(facts['judgmentCallCandidates'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
