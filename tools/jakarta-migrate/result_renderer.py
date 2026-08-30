"""Render migration-result.json as a self-contained HTML one-pager.

Reads the MigrationResult dict (as produced by migrate.run_migration) and writes
a fully static HTML file with all CSS inlined — no external assets, no JS.

Exported function
-----------------
render_html(result: dict, out_path: Path) -> None
"""
from __future__ import annotations

from html import escape
from pathlib import Path


# CSS palette matching final-plan.html
_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
    font-size: 14px;
    line-height: 1.6;
    background: #ffffff;
    color: #1f2328;
}
.page { max-width: 900px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 22px; font-weight: 700; }
h2 { font-size: 15px; font-weight: 600; margin: 28px 0 10px; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }
h3 { font-size: 13px; font-weight: 600; margin: 16px 0 6px; }
.subtitle { color: #57606a; font-size: 13px; margin-top: 4px; }
.header-band { padding: 20px 0 16px; border-bottom: 2px solid #e5e7eb; margin-bottom: 24px; }
.header-meta { display: flex; gap: 24px; margin-top: 10px; font-size: 12px; color: #57606a; }
.badge {
    display: inline-block; padding: 3px 10px; border-radius: 12px;
    font-size: 12px; font-weight: 600; letter-spacing: .03em; margin-top: 8px;
}
.badge-success { background: #d1fae5; color: #065f46; }
.badge-partial  { background: #fef3c7; color: #92400e; }
.badge-failed   { background: #fee2e2; color: #991b1b; }
.badge-skipped  { background: #f3f4f6; color: #6b7280; }
.tiles { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 24px; }
.tile {
    flex: 1 1 160px; background: #f7f8fa; border: 1px solid #e5e7eb;
    border-radius: 6px; padding: 14px 16px;
}
.tile .num { font-size: 26px; font-weight: 700; color: #1f2328; }
.tile .lbl { font-size: 11px; color: #57606a; margin-top: 2px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 20px; }
th { text-align: left; padding: 7px 10px; background: #f7f8fa; border-bottom: 2px solid #e5e7eb; font-weight: 600; }
td { padding: 6px 10px; border-bottom: 1px solid #e5e7eb; vertical-align: top; word-break: break-word; }
tr:last-child td { border-bottom: none; }
.tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.tag-success { background: #d1fae5; color: #065f46; }
.tag-failed  { background: #fee2e2; color: #991b1b; }
.tag-skipped { background: #f3f4f6; color: #6b7280; }
.tag-partial { background: #fef3c7; color: #92400e; }
.tag-manual  { background: #ede9fe; color: #5b21b6; }
.tag-replace { background: #dbeafe; color: #1e40af; }
.tag-remove  { background: #fee2e2; color: #991b1b; }
.tag-add     { background: #d1fae5; color: #065f46; }
.tag-bump    { background: #e0f2fe; color: #0369a1; }
.tag-nochange{ background: #f3f4f6; color: #6b7280; }
pre { background: #f7f8fa; border: 1px solid #e5e7eb; border-radius: 4px; padding: 10px 12px; font-size: 12px; overflow-x: auto; white-space: pre-wrap; word-break: break-all; }
.section-card { background: #f7f8fa; border: 1px solid #e5e7eb; border-radius: 6px; padding: 14px 16px; margin-bottom: 16px; }
.kv { display: flex; gap: 8px; font-size: 13px; margin-bottom: 4px; }
.kv .key { color: #57606a; min-width: 140px; }
.footer { text-align: center; font-size: 11px; color: #57606a; margin-top: 40px; padding-top: 14px; border-top: 1px solid #e5e7eb; }
"""


def _status_badge(status: str) -> str:
    cls_map = {
        "success": "badge-success",
        "partial": "badge-partial",
        "failed":  "badge-failed",
    }
    cls = cls_map.get(status, "badge-skipped")
    return f'<span class="badge {cls}">{escape(status.upper())}</span>'


def _step_tag(status: str) -> str:
    cls_map = {
        "success": "tag-success",
        "failed":  "tag-failed",
        "skipped": "tag-skipped",
        "partial": "tag-partial",
    }
    cls = cls_map.get(status, "tag-skipped")
    return f'<span class="tag {cls}">{escape(status)}</span>'


def _action_tag(action: str) -> str:
    cls_map = {
        "replace":         "tag-replace",
        "remove":          "tag-remove",
        "add":             "tag-add",
        "version_bump":    "tag-bump",
        "compiler_bump":   "tag-bump",
        "spi_rename":      "tag-replace",
        "no_rule":         "tag-nochange",
        "manual_required": "tag-manual",
    }
    cls = cls_map.get(action, "tag-nochange")
    return f'<span class="tag {cls}">{escape(action)}</span>'


def _collect_all_changes(steps: list[dict]) -> list[dict]:
    changes = []
    for step in steps:
        for ch in step.get("changes", []):
            ch_copy = dict(ch)
            ch_copy["_step"] = step.get("name", "")
            changes.append(ch_copy)
    return changes


def render_html(result: dict, out_path: Path) -> None:
    """Render migration-result.json dict to a self-contained HTML file at out_path."""
    steps = result.get("steps", [])
    skipped = result.get("skipped_items", [])
    manual = result.get("manual_required", [])
    build = result.get("build_result") or {}
    deploy = result.get("deploy_result") or {}
    status = result.get("status", "unknown")
    dry_run = result.get("dry_run", False)

    # Compute summary counts
    all_changes = _collect_all_changes(steps)
    non_trivial_changes = [
        c for c in all_changes
        if c.get("action") not in ("no_rule", "manual_required", "transformer_changed")
    ]
    transformer_changes = [c for c in all_changes if c.get("action") == "transformer_changed"]

    # -----------------------------------------------------------------------
    # Section: Header
    # -----------------------------------------------------------------------
    dry_run_note = ' <span style="font-size:12px;color:#92400e;background:#fef3c7;padding:2px 8px;border-radius:10px;">DRY RUN</span>' if dry_run else ""
    header_html = f"""
<div class="header-band">
  <h1>Jakarta EE 10 Migration Result{dry_run_note}</h1>
  <div class="subtitle">Java EE 8 → Jakarta EE 10 automated migration (EE-volution Layer C)</div>
  {_status_badge(status)}
</div>
"""

    # -----------------------------------------------------------------------
    # Section: Summary tiles
    # -----------------------------------------------------------------------
    tiles_html = f"""
<h2>Summary</h2>
<div class="tiles">
  <div class="tile"><div class="num">{len(steps)}</div><div class="lbl">Steps run</div></div>
  <div class="tile"><div class="num">{len(non_trivial_changes) + len(transformer_changes)}</div><div class="lbl">Changes applied</div></div>
  <div class="tile"><div class="num">{len(skipped)}</div><div class="lbl">Skipped (blocked)</div></div>
  <div class="tile"><div class="num">{len(manual)}</div><div class="lbl">Manual required</div></div>
</div>
"""

    # -----------------------------------------------------------------------
    # Section: Steps table
    # -----------------------------------------------------------------------
    steps_rows = ""
    for s in steps:
        n_changes = len(s.get("changes", []))
        errors = "; ".join(s.get("errors", []))
        notes = escape(s.get("notes", ""))
        steps_rows += f"""
<tr>
  <td><code>{escape(s.get('name',''))}</code></td>
  <td>{_step_tag(s.get('status',''))}</td>
  <td>{n_changes}</td>
  <td>{escape(errors) if errors else notes}</td>
</tr>"""

    steps_html = f"""
<h2>Steps</h2>
<table>
  <tr><th>Step</th><th>Status</th><th>Changes</th><th>Notes / Errors</th></tr>
  {steps_rows}
</table>
"""

    # -----------------------------------------------------------------------
    # Section: Changes Applied table (non-trivial)
    # -----------------------------------------------------------------------
    if non_trivial_changes or transformer_changes:
        change_rows = ""
        for c in non_trivial_changes:
            change_rows += f"""
<tr>
  <td style="max-width:180px">{escape(c.get('file',''))}</td>
  <td>{_action_tag(c.get('action',''))}</td>
  <td><code>{escape(c.get('old_coordinate',''))}</code></td>
  <td><code>{escape(c.get('new_coordinate',''))}</code></td>
  <td><code style="color:#57606a">{escape(c.get('map_key',''))}</code></td>
</tr>"""

        if transformer_changes:
            change_rows += f"""
<tr>
  <td colspan="4" style="color:#57606a"><em>… plus {len(transformer_changes)} files rewritten by Eclipse Transformer</em></td>
  <td></td>
</tr>"""

        changes_html = f"""
<h2>Changes Applied</h2>
<table>
  <tr><th>File</th><th>Action</th><th>Old</th><th>New</th><th>Map key</th></tr>
  {change_rows}
</table>
"""
    else:
        changes_html = "<h2>Changes Applied</h2><p style='color:#57606a'>No changes recorded.</p>"

    # -----------------------------------------------------------------------
    # Section: Skipped (blocked) items
    # -----------------------------------------------------------------------
    if skipped:
        skip_items = "".join(
            f'<li style="margin-bottom:6px"><code>{escape(wi_id)}</code> — status: blocked (requires manual resolution before re-running)</li>'
            for wi_id in skipped
        )
        skipped_html = f"""
<h2>Skipped Work Items (Blocked)</h2>
<ul style="margin-left:18px;font-size:13px">{skip_items}</ul>
"""
    else:
        skipped_html = ""

    # -----------------------------------------------------------------------
    # Section: Manual Required Items
    # -----------------------------------------------------------------------
    if manual:
        manual_rows = ""
        for m in manual:
            manual_rows += f"""
<tr>
  <td style="max-width:180px">{escape(m.get('file',''))}</td>
  <td><code>{escape(m.get('old_coordinate',''))}</code></td>
  <td>{escape(m.get('map_key',''))}</td>
</tr>"""
        manual_html = f"""
<h2>Manual Required Items</h2>
<p style="font-size:12px;color:#57606a;margin-bottom:10px">
  These items could not be automatically resolved.  Fix each one manually, then re-run the migration skill.
</p>
<table>
  <tr><th>File</th><th>Literal / Old value</th><th>Reason</th></tr>
  {manual_rows}
</table>
"""
    else:
        manual_html = ""

    # -----------------------------------------------------------------------
    # Section: Build Result
    # -----------------------------------------------------------------------
    if build:
        rc = build.get("return_code", "—")
        rc_badge = '<span class="tag tag-success">0</span>' if rc == 0 else f'<span class="tag tag-failed">{escape(str(rc))}</span>'
        stdout = escape(build.get("stdout_tail", ""))
        stderr = escape(build.get("stderr_tail", ""))
        build_html = f"""
<h2>Build Result (mvn package -DskipTests)</h2>
<div class="section-card">
  <div class="kv"><span class="key">Return code</span>{rc_badge}</div>
  {"<h3>stdout (last 50 lines)</h3><pre>" + stdout + "</pre>" if stdout else ""}
  {"<h3>stderr (last 20 lines)</h3><pre>" + stderr + "</pre>" if stderr else ""}
</div>
"""
    else:
        build_html = "<h2>Build Result</h2><p style='color:#57606a'>Build not run (dry_run or not reached).</p>"

    # -----------------------------------------------------------------------
    # Section: Deploy Result
    # -----------------------------------------------------------------------
    if deploy:
        lib_avail = deploy.get("liberty_available", False)
        dep_rc = deploy.get("return_code", "—")
        notes_str = escape(deploy.get("notes", ""))
        deploy_html = f"""
<h2>Deploy Result (mvn liberty:run)</h2>
<div class="section-card">
  <div class="kv"><span class="key">Liberty available</span>{'Yes' if lib_avail else 'No'}</div>
  <div class="kv"><span class="key">Return code</span>{escape(str(dep_rc))}</div>
  {"<div class='kv'><span class='key'>Notes</span>" + notes_str + "</div>" if notes_str else ""}
</div>
"""
    else:
        deploy_html = "<h2>Deploy Result</h2><p style='color:#57606a'>Deploy not run.</p>"

    # -----------------------------------------------------------------------
    # Footer
    # -----------------------------------------------------------------------
    footer_html = '<div class="footer">Made with IBM Bob</div>'

    # -----------------------------------------------------------------------
    # Assemble full HTML
    # -----------------------------------------------------------------------
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jakarta EE 10 Migration Result</title>
  <style>{_CSS}</style>
</head>
<body>
<div class="page">
{header_html}
{tiles_html}
{steps_html}
{changes_html}
{skipped_html}
{manual_html}
{build_html}
{deploy_html}
{footer_html}
</div>
</body>
</html>"""

    out_path.write_text(html, encoding="utf-8")
