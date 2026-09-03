"""Typed, non-searchable design recipe options for ORFS.

These switches describe how a design must be elaborated; they are not DSE
knobs. Keeping a closed registry prevents a bundle from smuggling arbitrary
Make or Tcl assignments into the execution environment.
"""

from __future__ import annotations

from typing import Any, Mapping


BOOL_OPTIONS = {
    "openroad_hierarchical": "OPENROAD_HIERARCHICAL",
    "swap_arith_operators": "SWAP_ARITH_OPERATORS",
    "remove_abc_buffers": "REMOVE_ABC_BUFFERS",
}


def validate_orfs_design_options(value: Mapping[str, Any] | None) -> dict[str, Any]:
    options = dict(value or {})
    unknown = sorted(set(options) - set(BOOL_OPTIONS))
    if unknown:
        raise ValueError(f"unknown ORFS design recipe options: {', '.join(unknown)}")
    result = {}
    for name, raw in options.items():
        if isinstance(raw, bool):
            result[name] = int(raw)
        elif isinstance(raw, int) and raw in {0, 1}:
            result[name] = raw
        else:
            raise ValueError(f"ORFS design option {name} must be boolean")
    return result


def orfs_design_option_config_lines(value: Mapping[str, Any] | None) -> tuple[str, ...]:
    options = validate_orfs_design_options(value)
    return tuple(f"export {BOOL_OPTIONS[name]} = {options[name]}" for name in sorted(options))
