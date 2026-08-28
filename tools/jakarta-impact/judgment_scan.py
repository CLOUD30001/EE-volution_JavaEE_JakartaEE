"""Pattern-based detection of javax-related risk that no rewrite tool resolves
mechanically: reflection on javax class names, custom serialization on classes
that carry javax-typed state, and ServiceLoader SPI registrations for javax
interfaces.

Build-system scope: Maven only.
Source files are expected at src/main/java and SPI files at
src/main/resources/META-INF/services — the standard Maven layout. Gradle and
Ant layouts (e.g. src/java, src/) are not supported and will silently produce
no results if the project uses them. Gradle/Ant support is future work.

Important scope limitation: these are regex-based CANDIDATE flags, not confirmed
risks. In particular the Serializable check flags any Serializable class in the
project regardless of whether its fields are actually javax-typed - telling the
two apart needs real type resolution (an AST/compiler-level check), which this
module deliberately does not attempt. Confirming which candidates are genuine
risk is Layer B's job, not this scanner's.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_REFLECTION_RE = re.compile(r'Class\s*\.\s*forName\s*\(\s*"(javax\.[A-Za-z0-9_.]+)"')
_SERIALIZABLE_RE = re.compile(r'\bimplements\b[^{;]*\bSerializable\b')
_SERIALIZATION_HOOK_RE = re.compile(r'\b(readObject|writeObject|readResolve|writeReplace)\s*\(')
_DYNAMIC_PROXY_RE = re.compile(r'Proxy\s*\.\s*newProxyInstance')


@dataclass
class JudgmentCallFinding:
    file: str
    kind: str
    detail: str


def scan_judgment_calls(repo_path: Path) -> list[JudgmentCallFinding]:
    findings: list[JudgmentCallFinding] = []

    java_root = repo_path / "src" / "main" / "java"
    if java_root.exists():
        for java_file in java_root.rglob("*.java"):
            text = java_file.read_text(encoding="utf-8", errors="replace")
            rel = java_file.relative_to(repo_path).as_posix()

            for m in _REFLECTION_RE.finditer(text):
                findings.append(JudgmentCallFinding(
                    file=rel, kind="reflection_string_literal",
                    detail=f'Class.forName("{m.group(1)}") - string literal invisible to import-based tooling',
                ))

            if _DYNAMIC_PROXY_RE.search(text):
                findings.append(JudgmentCallFinding(
                    file=rel, kind="dynamic_proxy",
                    detail="Proxy.newProxyInstance(...) found - verify any javax interface it implements dynamically",
                ))

            if _SERIALIZABLE_RE.search(text):
                has_hook = bool(_SERIALIZATION_HOOK_RE.search(text))
                findings.append(JudgmentCallFinding(
                    file=rel, kind="serializable_class",
                    detail=(
                        "implements Serializable, with custom read/write hooks - check field types by hand"
                        if has_hook else
                        "implements Serializable (no custom read/write hooks found) - low risk unless a field is javax-typed"
                    ),
                ))

    spi_dir = repo_path / "src" / "main" / "resources" / "META-INF" / "services"
    if spi_dir.exists():
        for f in spi_dir.glob("javax.*"):
            findings.append(JudgmentCallFinding(
                file=f.relative_to(repo_path).as_posix(),
                kind="spi_registration",
                detail=f"ServiceLoader registration file named after a javax interface: {f.name}",
            ))

    return findings
