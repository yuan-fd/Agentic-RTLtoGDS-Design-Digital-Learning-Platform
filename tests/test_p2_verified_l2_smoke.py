from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_p2_smoke_pins_and_contains_its_historical_rtlscout_source() -> None:
    """The replay helper must fail closed before it imports legacy evidence."""
    source = (ROOT / "scripts/run_p2_verified_l2_smoke.py").read_text(encoding="utf-8")
    assert "SOURCE_DB_SHA256" in source
    assert "source_db_sha256 != SOURCE_DB_SHA256" in source
    assert "source_rtl_path.relative_to(source_workspace)" in source
    assert "pinned RTLScout artifact escapes its Runtime workspace" in source
    assert "digest(source_rtl_path) != source_rtl[\"sha256\"]" in source
