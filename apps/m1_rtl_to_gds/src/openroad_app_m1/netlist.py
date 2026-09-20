"""Deterministic SVG rendering for a bounded gate-level netlist excerpt."""

from __future__ import annotations

import html
import re


_CELL = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_$]*)\s+([A-Za-z][A-Za-z0-9_$]*)\s*\(")


def render_netlist_svg(source: str) -> str | None:
    cells = []
    for line in source.splitlines():
        match = _CELL.match(line)
        if match:
            cells.append((match.group(1), match.group(2)))
    if not cells:
        return None
    width = 280
    height = max(120, 70 + len(cells) * 52)
    rows = []
    for index, (cell, instance) in enumerate(cells):
        y = 32 + index * 52
        rows.append(
            f'<g data-instance="{html.escape(instance, quote=True)}">'
            f'<rect x="24" y="{y}" width="232" height="34" rx="2" fill="#f4f4f0" stroke="#151515"/>'
            f'<text x="36" y="{y + 15}" font-family="monospace" font-size="11" fill="#151515">'
            f'{html.escape(cell)}</text>'
            f'<text x="36" y="{y + 28}" font-family="monospace" font-size="10" fill="#555">'
            f'{html.escape(instance)}</text></g>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="Gate-level netlist with {len(cells)} cells">'
        + "".join(rows) + "</svg>"
    )
