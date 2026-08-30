"""Orchestrate all migration steps for a Java EE 8 → Jakarta EE 10 migration.

This is the core business-logic module.  It sequences nine migration steps, manages
disk writes, collects all ChangeRecords into a unified MigrationResult, and writes
migration-result.json.  The MCP server (jakarta_migrate_server.py) calls
run_migration() as its single entry point.

Steps (in order)
----------------
1  preflight           — validate reports, surface blockers, check Git, check Liberty
2  transform_source    — run Eclipse Transformer on src/main/ tree
3  apply_transformer   — copy src-transformed/ back over src/
4  gap_fill            — string literals + Facelets URI patches
5  patch_pom           — Maven coordinate changes
6  patch_server_xml    — Liberty feature name changes
7  git_commit          — commit all changes (skipped if Git unavailable)
8  build_verify        — mvn package -DskipTests
9  deploy              — mvn liberty:run (skipped if Liberty unavailable)

dry_run=True
    Executes all read/compute steps but writes NOTHING to disk and skips
    git_commit, build_verify, and deploy.

Exported function
-----------------
run_migration(repo_path, reports_dir, java_home, mvn_cmd, work_dir, dry_run)
    -> MigrationResult

Exported helper
---------------
write_migration_result(result, out_path)
    Serialises MigrationResult to JSON at out_path.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path additions for sibling imports
# ---------------------------------------------------------------------------
import sys
_this_dir = Path(__file__).resolve().parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

import gap_filler
import pom_patcher
import server_xml_patcher
from pom_patcher import ChangeRecord, load_dependency_map
from transformer_source_runner import SourceTransformerRunner

_DEP_MAP_PATH = _this_dir / "dependency_map.json"
_FEATURE_MAP_PATH = _this_dir / "feature_map.json"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    name: str
    status: str          # "success" | "skipped" | "failed"
    changes: list[dict]  # serialised ChangeRecords
    errors: list[str]
    notes: str = ""


@dataclass
class BuildResult:
    return_code: int
    stdout_tail: str
    stderr_tail: str


@dataclass
class DeployResult:
    return_code: int
    liberty_available: bool
    notes: str = ""


@dataclass
class PreflightResult:
    ok: bool
    hard_errors: list[str]
    skipped_items: list[str]    # WI IDs with status == "blocked"
    git_available: bool
    liberty_available: bool
    sign_off_status: str
    final_plan: dict


@dataclass
class MigrationResult:
    status: str                       # "success" | "partial" | "failed"
    steps: list[StepResult]
    skipped_items: list[str]
    manual_required: list[dict]       # serialised ChangeRecords with action="manual_required"
    build_result: dict | None
    deploy_result: dict | None
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _changes_to_dicts(changes: list[ChangeRecord]) -> list[dict]:
    return [asdict(c) for c in changes]


def _tail(text: str, n: int = 50) -> str:
    """Return the last n lines of text."""
    lines = text.splitlines()
    return "\n".join(lines[-n:]) if len(lines) > n else text


def _write_changes(changes_by_file: dict[Path, str], dry_run: bool) -> None:
    """Write patched file content to disk unless dry_run=True."""
    if dry_run:
        return
    for file_path, content in changes_by_file.items():
        file_path.write_text(content, encoding="utf-8")


def _write_spi_renames(changes: list[ChangeRecord], dry_run: bool) -> None:
    """Perform SPI file renames described by spi_rename ChangeRecords."""
    if dry_run:
        return
    for cr in changes:
        if cr.action != "spi_rename":
            continue
        old_path = Path(cr.old_coordinate)
        new_path = Path(cr.new_coordinate)
        if old_path.exists():
            # Update contents (javax→jakarta) then rename
            content = old_path.read_text(encoding="utf-8", errors="replace")
            # Apply the same literal substitution to file contents
            from gap_filler import _resolve_literal  # noqa: PLC0415
            new_content = content
            for line in content.splitlines():
                for word in line.split():
                    if word.startswith("javax."):
                        resolved = _resolve_literal(word)
                        if resolved:
                            new_content = new_content.replace(word, resolved)
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_text(new_content, encoding="utf-8")
            old_path.unlink()


# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

def _preflight(repo_path: Path, reports_dir: Path) -> PreflightResult:
    hard_errors: list[str] = []
    skipped_items: list[str] = []
    git_available = False
    liberty_available = False
    sign_off_status = "unknown"
    final_plan: dict = {}

    # Hard-stop checks: required JSON files
    for fname in ("discovery-report.json", "impact-facts.json", "final-plan.json"):
        if not (reports_dir / fname).exists():
            hard_errors.append(f"Required report missing: {reports_dir / fname}")

    if hard_errors:
        return PreflightResult(
            ok=False,
            hard_errors=hard_errors,
            skipped_items=[],
            git_available=False,
            liberty_available=False,
            sign_off_status="unknown",
            final_plan={},
        )

    # Parse final-plan.json for blocked WIs
    final_plan_path = reports_dir / "final-plan.json"
    try:
        final_plan = json.loads(final_plan_path.read_text(encoding="utf-8"))
        sign_off_status = final_plan.get("signOff", {}).get("status", "unknown")
        for wi in final_plan.get("workItems", []):
            if wi.get("status") == "blocked":
                skipped_items.append(wi.get("id", "?"))
    except (json.JSONDecodeError, OSError) as exc:
        hard_errors.append(f"Cannot parse final-plan.json: {exc}")

    # Git availability check
    try:
        proc = subprocess.run(
            ["git", "status"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        git_available = proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        git_available = False

    # Liberty availability check
    try:
        proc = subprocess.run(
            ["mvn", "liberty:version", "-q", "-f", str(repo_path / "pom.xml")],
            capture_output=True,
            text=True,
            timeout=60,
        )
        liberty_available = proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # Check for existing liberty install under target/
        liberty_bin = repo_path / "target" / "liberty" / "wlp" / "bin" / "server"
        liberty_available = liberty_bin.exists()

    return PreflightResult(
        ok=len(hard_errors) == 0,
        hard_errors=hard_errors,
        skipped_items=skipped_items,
        git_available=git_available,
        liberty_available=liberty_available,
        sign_off_status=sign_off_status,
        final_plan=final_plan,
    )


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git_commit(repo_path: Path, message: str, dry_run: bool) -> StepResult:
    if dry_run:
        return StepResult(
            name="git_commit",
            status="skipped",
            changes=[],
            errors=[],
            notes="dry_run=True — no commit made",
        )
    try:
        subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=repo_path, check=True, capture_output=True)
        return StepResult(
            name="git_commit",
            status="success",
            changes=[],
            errors=[],
            notes=f"Committed: {message}",
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"").decode(errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        return StepResult(
            name="git_commit",
            status="failed",
            changes=[],
            errors=[err or str(exc)],
            notes="Git commit failed — migration files are written but not committed",
        )


# ---------------------------------------------------------------------------
# Build + deploy helpers
# ---------------------------------------------------------------------------

def _run_build(repo_path: Path, mvn_cmd: str) -> BuildResult:
    proc = subprocess.run(
        [mvn_cmd, "package", "-DskipTests", "-f", str(repo_path / "pom.xml")],
        capture_output=True,
        text=True,
    )
    return BuildResult(
        return_code=proc.returncode,
        stdout_tail=_tail(proc.stdout or "", 50),
        stderr_tail=_tail(proc.stderr or "", 20),
    )


def _run_deploy(
    repo_path: Path,
    mvn_cmd: str,
    liberty_available: bool,
    dry_run: bool,
) -> DeployResult:
    if not liberty_available or dry_run:
        return DeployResult(
            return_code=-1,
            liberty_available=liberty_available,
            notes="Deploy skipped — liberty_available=False or dry_run=True",
        )
    try:
        proc = subprocess.run(
            [mvn_cmd, "liberty:run", "-f", str(repo_path / "pom.xml")],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return DeployResult(
            return_code=proc.returncode,
            liberty_available=True,
        )
    except subprocess.TimeoutExpired:
        return DeployResult(
            return_code=-2,
            liberty_available=True,
            notes="liberty:run timed out after 120s (server may still be starting)",
        )


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_migration(
    repo_path: str | Path,
    reports_dir: str | Path,
    java_home: str,
    mvn_cmd: str = "mvn",
    work_dir: str | Path | None = None,
    dry_run: bool = False,
) -> MigrationResult:
    """Execute all nine migration steps and return a MigrationResult.

    Args:
        repo_path:    Path to the Maven project root (must contain pom.xml).
        reports_dir:  Directory containing discovery-report.json, impact-facts.json,
                      and final-plan.json.
        java_home:    JDK 11+ home for running Eclipse Transformer.
        mvn_cmd:      Maven executable (default "mvn").
        work_dir:     Scratch directory for intermediate files.
                      Defaults to <repo_path>/target/jakarta-migrate.
        dry_run:      If True, compute but write nothing to disk.

    Returns:
        MigrationResult with populated steps, skipped_items, build_result etc.
        Also writes migration-result.json to reports_dir (unless dry_run=True).
    """
    repo_path = Path(repo_path)
    reports_dir = Path(reports_dir)
    work_dir = Path(work_dir) if work_dir else repo_path / "target" / "jakarta-migrate"
    work_dir.mkdir(parents=True, exist_ok=True)

    steps: list[StepResult] = []
    all_manual: list[dict] = []

    # -----------------------------------------------------------------------
    # Step 1 — Pre-flight
    # -----------------------------------------------------------------------
    preflight = _preflight(repo_path, reports_dir)
    preflight_notes = ""
    if preflight.skipped_items:
        preflight_notes = f"Blocked WIs (will be skipped): {', '.join(preflight.skipped_items)}"
    if not preflight.git_available:
        preflight_notes += " | Git unavailable — changes will not be committed"
    if preflight.sign_off_status == "draft":
        preflight_notes += " | final-plan.json sign-off status is 'draft'"

    if not preflight.ok:
        steps.append(StepResult(
            name="preflight",
            status="failed",
            changes=[],
            errors=preflight.hard_errors,
            notes="Hard errors — migration cannot proceed",
        ))
        return MigrationResult(
            status="failed",
            steps=steps,
            skipped_items=[],
            manual_required=[],
            build_result=None,
            deploy_result=None,
            dry_run=dry_run,
        )

    steps.append(StepResult(
        name="preflight",
        status="success",
        changes=[],
        errors=[],
        notes=preflight_notes.strip(" |"),
    ))

    # Load maps
    dep_map = load_dependency_map(_DEP_MAP_PATH)
    feature_map: dict[str, str] = json.loads(_FEATURE_MAP_PATH.read_text(encoding="utf-8"))
    discovery_report: dict = json.loads(
        (reports_dir / "discovery-report.json").read_text(encoding="utf-8")
    )

    # -----------------------------------------------------------------------
    # Step 2 — Transform source (Eclipse Transformer on src/main/)
    # -----------------------------------------------------------------------
    src_main = repo_path / "src" / "main"
    transform_errors: list[str] = []
    transformer_result = None
    try:
        runner = SourceTransformerRunner(java_home=java_home, work_dir=work_dir / "transformer")
        transformer_result = runner.run(src_main, mvn_cmd=mvn_cmd)
        transform_status = "success" if transformer_result.return_code == 0 else "failed"
        if transformer_result.return_code != 0:
            transform_errors.append(
                f"Transformer exited with code {transformer_result.return_code}"
            )
        transform_changes = [
            {"file": f, "action": "transformer_changed", "old_coordinate": "", "new_coordinate": "", "map_key": ""}
            for f in transformer_result.changed_files
        ]
        steps.append(StepResult(
            name="transform_source",
            status=transform_status,
            changes=transform_changes,
            errors=transform_errors,
            notes=f"{len(transformer_result.changed_files)} files changed by Transformer",
        ))
    except Exception as exc:
        steps.append(StepResult(
            name="transform_source",
            status="failed",
            changes=[],
            errors=[str(exc)],
            notes="Eclipse Transformer invocation failed",
        ))
        transform_status = "failed"

    # -----------------------------------------------------------------------
    # Step 3 — Apply Transformer output (copy src-transformed/ back over src/main/)
    # -----------------------------------------------------------------------
    apply_errors: list[str] = []
    if transformer_result and transformer_result.return_code == 0:
        if not dry_run:
            try:
                transformed_dir = transformer_result.output_dir
                shutil.copytree(
                    transformed_dir,
                    src_main,
                    dirs_exist_ok=True,
                )
                apply_notes = f"Copied transformed output from {transformed_dir} over {src_main}"
            except Exception as exc:
                apply_errors.append(str(exc))
                apply_notes = "Copy failed"
        else:
            apply_notes = "dry_run=True — transformer output not applied to source tree"
        steps.append(StepResult(
            name="apply_transformer_output",
            status="skipped" if dry_run else ("failed" if apply_errors else "success"),
            changes=[],
            errors=apply_errors,
            notes=apply_notes,
        ))
    else:
        steps.append(StepResult(
            name="apply_transformer_output",
            status="skipped",
            changes=[],
            errors=[],
            notes="Skipped — transform_source did not complete successfully",
        ))

    # -----------------------------------------------------------------------
    # Step 4 — Gap fill (string literals, Facelets URIs, SPI renames)
    # -----------------------------------------------------------------------
    try:
        patched_files, gap_changes = gap_filler.fill_gaps(repo_path, discovery_report)
        _write_changes(patched_files, dry_run)
        manual_from_gaps = [asdict(c) for c in gap_changes if c.action == "manual_required"]
        all_manual.extend(manual_from_gaps)
        spi_changes = [c for c in gap_changes if c.action == "spi_rename"]
        _write_spi_renames(spi_changes, dry_run)
        steps.append(StepResult(
            name="gap_fill",
            status="success",
            changes=_changes_to_dicts([c for c in gap_changes if c.action != "manual_required"]),
            errors=[],
            notes=(
                f"{len(patched_files)} files patched, "
                f"{len(spi_changes)} SPI renames, "
                f"{len(manual_from_gaps)} manual_required items"
            ),
        ))
    except Exception as exc:
        steps.append(StepResult(
            name="gap_fill",
            status="failed",
            changes=[],
            errors=[str(exc)],
        ))

    # -----------------------------------------------------------------------
    # Step 5 — Patch pom.xml
    # -----------------------------------------------------------------------
    pom_path = repo_path / "pom.xml"
    try:
        patched_pom, pom_changes = pom_patcher.patch_pom(pom_path, dep_map)
        if not dry_run:
            pom_path.write_text(patched_pom, encoding="utf-8")
        steps.append(StepResult(
            name="patch_pom",
            status="success",
            changes=_changes_to_dicts(pom_changes),
            errors=[],
            notes=f"{len(pom_changes)} pom.xml changes applied",
        ))
    except Exception as exc:
        steps.append(StepResult(
            name="patch_pom",
            status="failed",
            changes=[],
            errors=[str(exc)],
        ))

    # -----------------------------------------------------------------------
    # Step 6 — Patch server.xml
    # -----------------------------------------------------------------------
    # Find server.xml — check both common locations
    server_xml_candidates = [
        repo_path / "src" / "main" / "liberty" / "config" / "server.xml",
        repo_path / "src" / "main" / "server" / "server.xml",
    ]
    server_xml_path = next((p for p in server_xml_candidates if p.exists()), None)

    if server_xml_path:
        try:
            patched_server, server_changes = server_xml_patcher.patch_server_xml(
                server_xml_path, feature_map
            )
            if not dry_run:
                server_xml_path.write_text(patched_server, encoding="utf-8")
            steps.append(StepResult(
                name="patch_server_xml",
                status="success",
                changes=_changes_to_dicts(server_changes),
                errors=[],
                notes=f"{len([c for c in server_changes if c.action == 'replace'])} features updated",
            ))
        except Exception as exc:
            steps.append(StepResult(
                name="patch_server_xml",
                status="failed",
                changes=[],
                errors=[str(exc)],
            ))
    else:
        steps.append(StepResult(
            name="patch_server_xml",
            status="skipped",
            changes=[],
            errors=[],
            notes="server.xml not found — Liberty server config absent or at non-standard path",
        ))

    # -----------------------------------------------------------------------
    # Step 7 — Git commit
    # -----------------------------------------------------------------------
    if preflight.git_available:
        git_step = _git_commit(
            repo_path,
            "chore: migrate Java EE 8 → Jakarta EE 10 (automated by ee-volution-migrate)",
            dry_run,
        )
    else:
        git_step = StepResult(
            name="git_commit",
            status="skipped",
            changes=[],
            errors=[],
            notes="Git not available — skipped (not an error)",
        )
    steps.append(git_step)

    # -----------------------------------------------------------------------
    # Step 8 — Build verify
    # -----------------------------------------------------------------------
    if not dry_run:
        build_result_obj = _run_build(repo_path, mvn_cmd)
        build_status = "success" if build_result_obj.return_code == 0 else "failed"
        steps.append(StepResult(
            name="build_verify",
            status=build_status,
            changes=[],
            errors=[] if build_result_obj.return_code == 0 else [
                f"mvn package returned {build_result_obj.return_code}"
            ],
            notes=f"exit code {build_result_obj.return_code}",
        ))
        build_result_dict: dict | None = asdict(build_result_obj)
    else:
        steps.append(StepResult(
            name="build_verify",
            status="skipped",
            changes=[],
            errors=[],
            notes="dry_run=True — build not run",
        ))
        build_result_dict = None

    # -----------------------------------------------------------------------
    # Step 9 — Deploy
    # -----------------------------------------------------------------------
    if not dry_run:
        deploy_obj = _run_deploy(repo_path, mvn_cmd, preflight.liberty_available, dry_run)
        deploy_status = (
            "skipped" if not preflight.liberty_available
            else ("success" if deploy_obj.return_code == 0 else "failed")
        )
        steps.append(StepResult(
            name="deploy",
            status=deploy_status,
            changes=[],
            errors=[] if deploy_obj.return_code in (0, -1, -2) else [
                f"liberty:run returned {deploy_obj.return_code}"
            ],
            notes=deploy_obj.notes or f"exit code {deploy_obj.return_code}",
        ))
        deploy_result_dict: dict | None = asdict(deploy_obj)
    else:
        steps.append(StepResult(
            name="deploy",
            status="skipped",
            changes=[],
            errors=[],
            notes="dry_run=True — deploy not run",
        ))
        deploy_result_dict = None

    # -----------------------------------------------------------------------
    # Compute overall status
    # -----------------------------------------------------------------------
    failed_steps = [s for s in steps if s.status == "failed"]
    if not failed_steps:
        overall = "success" if not all_manual else "partial"
    elif len(failed_steps) == len(steps):
        overall = "failed"
    else:
        overall = "partial"

    result = MigrationResult(
        status=overall,
        steps=steps,
        skipped_items=preflight.skipped_items,
        manual_required=all_manual,
        build_result=build_result_dict,
        deploy_result=deploy_result_dict,
        dry_run=dry_run,
    )

    # Write migration-result.json
    out_path = reports_dir / "migration-result.json"
    write_migration_result(result, out_path)

    return result


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def write_migration_result(result: MigrationResult, out_path: Path) -> None:
    """Serialise MigrationResult to JSON at out_path."""

    def _to_dict(obj: Any) -> Any:
        if hasattr(obj, "__dataclass_fields__"):
            return {k: _to_dict(v) for k, v in asdict(obj).items()}
        if isinstance(obj, list):
            return [_to_dict(i) for i in obj]
        if isinstance(obj, dict):
            return {k: _to_dict(v) for k, v in obj.items()}
        return obj

    data = _to_dict(result)
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
