"""Runs Eclipse Transformer's JakartaTransformerCLI against a built WAR and parses
its verbose log into structured per-resource results.

Invocation and log format were verified by hand against
org.eclipse.transformer.cli:1.0.0 / org.eclipse.transformer.jakarta:1.0.0
(EPL-2.0 / Apache-2.0) on 2026-08-20 - see tools/jakarta-impact/README.md.

Build-system scope: Maven only.
This module assumes the standard Maven project layout: source under src/main/java,
resources under src/main/resources, webapp under src/main/webapp, and build output
under target/. Gradle and Ant are not supported and will not be added here — that
is tracked as future work at the pipeline level.

Two things worth knowing before trusting this module's output:

1. Eclipse Transformer never modifies its input; it always writes a new
   transformed copy to a separate output path. There is a --dryrun (-d) flag,
   but empirically it did NOT skip writing the output file - so "dry run" safety
   here comes from writing to a throwaway work_dir, not from that flag.
2. Requires a JDK new enough to load the transformer jars (JDK 8 failed with
   UnsupportedClassVersionError in testing; JDK 19 worked). Pass a java_home
   that points at a modern JDK - this is unrelated to whatever JDK the target
   project itself compiles with.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
TRANSFORMER_DEPS_POM = _PACKAGE_DIR.parent / "pom-templates" / "transformer-deps-pom.xml"

_STOP_PROCESSING_RE = re.compile(
    r"Stop processing \[ (?P<path>.+?) \] using \[ (?P<action>[\w ]+? Action) \] "
    r"took \[ \d+ms \]: (?P<result>.+)$"
)
_SUMMARY_ROW_RE = re.compile(
    r"\[\s*(?P<label>[\w ]+?)\s*\]\s*\[\s*(?P<total>\d+)\s*\]\s*"
    r"Unchanged \[\s*(?P<unchanged>\d+)\s*\]\s*Changed \[\s*(?P<changed>\d+)\s*\]"
)


@dataclass
class ResourceResult:
    path: str          # WAR-relative path, forward slashes, e.g. "WEB-INF/classes/com/acme/legacy/entity/Order.class"
    action: str         # e.g. "Class Action", "Text Action", "XML Action"
    changed: bool
    detail: str         # raw trailing text, e.g. "Content changes" / "No changes"


@dataclass
class TransformRun:
    return_code: int
    resources: list[ResourceResult] = field(default_factory=list)
    action_summary: dict[str, dict[str, int]] = field(default_factory=dict)
    raw_log_path: Path | None = None

    def matching(self, prefix: str) -> list[ResourceResult]:
        return [r for r in self.resources if r.path.startswith(prefix)]

    def by_path(self, path: str) -> ResourceResult | None:
        for r in self.resources:
            if r.path == path:
                return r
        return None


class TransformerRunner:
    def __init__(self, java_home: str, work_dir: Path):
        self.java_bin = str(Path(java_home) / "bin" / "java")
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._dep_jars: list[Path] | None = None

    def _ensure_dependencies(self, mvn_cmd: str) -> list[Path]:
        if self._dep_jars is not None:
            return self._dep_jars

        dep_project = self.work_dir / "transformer-deps"
        target_dep_dir = dep_project / "target" / "dependency"

        if not target_dep_dir.exists():
            dep_project.mkdir(parents=True, exist_ok=True)
            (dep_project / "pom.xml").write_text(
                TRANSFORMER_DEPS_POM.read_text(encoding="utf-8"), encoding="utf-8"
            )
            subprocess.run(
                [mvn_cmd, "-q", "dependency:copy-dependencies", "-DincludeScope=runtime"],
                cwd=dep_project,
                check=True,
            )

        self._dep_jars = sorted(target_dep_dir.glob("*.jar"))
        if not self._dep_jars:
            raise RuntimeError(
                f"No dependency jars found under {target_dep_dir} - "
                "dependency resolution may have failed silently."
            )
        return self._dep_jars

    def run(self, input_war: Path, mvn_cmd: str = "mvn") -> TransformRun:
        jars = self._ensure_dependencies(mvn_cmd)
        classpath = os.pathsep.join(str(j) for j in jars)

        output_war = self.work_dir / f"{input_war.stem}.transformed.war"
        if output_war.exists():
            output_war.unlink()
        log_path = self.work_dir / f"{input_war.stem}.transform.log"

        cmd = [
            self.java_bin,
            "-cp", classpath,
            "org.eclipse.transformer.cli.JakartaTransformerCLI",
            str(input_war), str(output_war),
            "-o",  # overwrite - output_war was just cleared above, but avoids a stale-run false failure
            "-v",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        log_path.write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")

        return self._parse_log(log_path, proc.returncode)

    @staticmethod
    def _parse_log(log_path: Path, return_code: int) -> TransformRun:
        run = TransformRun(return_code=return_code, raw_log_path=log_path)
        text = log_path.read_text(encoding="utf-8", errors="replace")

        for line in text.splitlines():
            m = _STOP_PROCESSING_RE.search(line)
            if m:
                result = m.group("result").strip()
                run.resources.append(ResourceResult(
                    path=m.group("path"),
                    action=m.group("action"),
                    changed=not result.lower().startswith("no changes"),
                    detail=result,
                ))
                continue
            sm = _SUMMARY_ROW_RE.search(line)
            if sm and "Unaccepted" not in line:
                run.action_summary[sm.group("label").strip()] = {
                    "total": int(sm.group("total")),
                    "unchanged": int(sm.group("unchanged")),
                    "changed": int(sm.group("changed")),
                }

        return run


def _assert_maven_project(repo_path: Path) -> None:
    """Raise ValueError immediately if repo_path does not look like a Maven project.

    Only Maven is supported (Gradle and Ant are future work). Failing fast here
    gives a clear error rather than a confusing FileNotFoundError when
    target/*.war is missing.
    """
    if not (repo_path / "pom.xml").exists():
        raise ValueError(
            f"No pom.xml found at '{repo_path}'. "
            "Only Maven projects are supported — Gradle and Ant support is not "
            "implemented and is tracked as future work."
        )


def find_built_war(repo_path: Path) -> Path:
    """Locate the project WAR under <repo>/target/.

    Validates that the project is Maven-based before searching, so callers get
    a clear error when pointed at a Gradle or Ant project by mistake.
    """
    _assert_maven_project(repo_path)
    candidates = sorted((repo_path / "target").glob("*.war")) if (repo_path / "target").exists() else []
    candidates = [c for c in candidates if not c.name.endswith(".transformed.war")]
    if not candidates:
        raise FileNotFoundError(
            f"No .war found under {repo_path / 'target'} - run `mvn package` first."
        )
    return candidates[0]
