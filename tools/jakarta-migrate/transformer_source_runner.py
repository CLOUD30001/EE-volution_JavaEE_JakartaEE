"""Run Eclipse Transformer against a source directory (not a WAR).

Transformer accepts a directory as both input and output — it recurses into it
applying Text Action to .java files and XML Action to descriptor files.  This
module wraps that directory-mode invocation.

Crucially, the source tree is NEVER modified directly.  The input directory is
first copied to a staging area under work_dir; Transformer writes its output to
a separate output directory.  The caller (migrate.py) copies the output back over
the source tree after reviewing it.

Reuses TransformerRunner._ensure_dependencies() from the jakarta-impact package
for dependency resolution (same POM template, same JAR cache logic) — does not
duplicate that code.

Exported class
--------------
SourceTransformerRunner(java_home, work_dir)
    .run(source_dir, mvn_cmd="mvn") -> TransformSourceRun

Exported dataclass
------------------
TransformSourceRun:
    return_code      : int
    output_dir       : Path  (work_dir/src-transformed/)
    changed_files    : list[str]  (paths relative to output_dir)
    unchanged_files  : list[str]
    log_path         : Path
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Add the jakarta-impact directory to sys.path so we can import TransformerRunner.
import sys
_impact_dir = Path(__file__).resolve().parent.parent / "jakarta-impact"
if str(_impact_dir) not in sys.path:
    sys.path.insert(0, str(_impact_dir))

from transformer_runner import TransformerRunner  # noqa: E402


@dataclass
class TransformSourceRun:
    """Result of running Eclipse Transformer against a source directory."""
    return_code: int
    output_dir: Path
    changed_files: list[str] = field(default_factory=list)
    unchanged_files: list[str] = field(default_factory=list)
    log_path: Path | None = None


class SourceTransformerRunner:
    """Run Eclipse Transformer against a source directory.

    The source directory is copied to work_dir/src-copy/ before transformation.
    Transformer output is written to work_dir/src-transformed/.
    The original source_dir is never touched.

    Args:
        java_home:  Path to a JDK 11+ installation.  Used only to run the Transformer
                    tool itself — unrelated to the project's compile JDK.
        work_dir:   Directory where intermediate files (dep jars, copies, logs) are kept.
    """

    def __init__(self, java_home: str, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)
        # Delegate dependency resolution to the existing TransformerRunner.
        self._dep_runner = TransformerRunner(java_home=java_home, work_dir=work_dir)
        self._java_bin = str(Path(java_home) / "bin" / "java")

    def run(self, source_dir: Path, mvn_cmd: str = "mvn") -> TransformSourceRun:
        """Copy source_dir to a staging location, run Transformer, return results.

        Steps:
          1. Copy source_dir → work_dir/src-copy/  (clean copy every run)
          2. Resolve Transformer JARs via Maven (cached after first run)
          3. Run JakartaTransformerCLI on src-copy/ → src-transformed/
          4. Parse log → changed_files / unchanged_files lists
          5. Return TransformSourceRun

        Args:
            source_dir:  Absolute path to the source directory to transform
                         (typically <repo>/src/main/java or the whole <repo>/src tree).
            mvn_cmd:     Maven executable (default "mvn").

        Returns:
            TransformSourceRun with populated changed_files and unchanged_files.
        """
        src_copy = self.work_dir / "src-copy"
        src_transformed = self.work_dir / "src-transformed"
        log_path = self.work_dir / "transform-source.log"

        # Clean and recreate staging dirs
        if src_copy.exists():
            shutil.rmtree(src_copy)
        if src_transformed.exists():
            shutil.rmtree(src_transformed)

        shutil.copytree(source_dir, src_copy)
        src_transformed.mkdir(parents=True, exist_ok=True)

        # Resolve Transformer JAR dependencies (same cache used by WAR-mode runs)
        jars = self._dep_runner._ensure_dependencies(mvn_cmd)
        classpath = os.pathsep.join(str(j) for j in jars)

        cmd = [
            self._java_bin,
            "-cp", classpath,
            "org.eclipse.transformer.cli.JakartaTransformerCLI",
            str(src_copy),
            str(src_transformed),
            "-o",   # overwrite output dir if it exists
            "-v",   # verbose — needed to parse changed/unchanged file list
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        log_path.write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")

        result = self._parse_source_log(log_path, proc.returncode, src_transformed)
        return result

    @staticmethod
    def _parse_source_log(
        log_path: Path,
        return_code: int,
        output_dir: Path,
    ) -> TransformSourceRun:
        """Parse the Transformer verbose log produced for a directory run.

        Reuses the same "Stop processing" line pattern as TransformerRunner._parse_log
        but collects file-level results relative to output_dir rather than WAR entries.
        """
        from transformer_runner import _STOP_PROCESSING_RE  # noqa: PLC0415

        changed: list[str] = []
        unchanged: list[str] = []

        text = log_path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            m = _STOP_PROCESSING_RE.search(line)
            if m:
                file_path = m.group("path")
                result = m.group("result").strip()
                if result.lower().startswith("no changes"):
                    unchanged.append(file_path)
                else:
                    changed.append(file_path)

        return TransformSourceRun(
            return_code=return_code,
            output_dir=output_dir,
            changed_files=changed,
            unchanged_files=unchanged,
            log_path=log_path,
        )
