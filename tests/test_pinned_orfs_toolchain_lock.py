import hashlib
import json
from pathlib import Path

from openroad_platform_execution import validate_pinned_orfs_toolchain


ROOT = Path(__file__).resolve().parents[1]


def test_registered_orfs_patch_is_content_addressed_and_minimal():
    lock = json.loads((
        ROOT / "integrations/orfs/orfs-industrial-v2.lock.json"
    ).read_text())
    assert lock["orfs_commit"] == "51ad1231a231ee85234c06db807688d029b85c35"
    assert len(lock["patches"]) == 1
    patch_row = lock["patches"][0]
    patch = ROOT / patch_row["path"]
    assert hashlib.sha256(patch.read_bytes()).hexdigest() == patch_row["sha256"]
    text = patch.read_text()
    assert "gui::show" in text
    assert "-source_step_tcl" not in text
    assert "+source_step_tcl" not in text
    assert patch_row["sha256"] == lock["orfs_binary_patch_sha256"]


def test_pinned_orfs_runtime_gate_verifies_source_patch_and_binaries_read_only():
    evidence = validate_pinned_orfs_toolchain(
        ROOT / "var/toolchains/orfs-51ad1231-clean",
        ROOT / "integrations/orfs/orfs-industrial-v2.lock.json",
    )
    assert evidence["validated"] is True
    assert evidence["orfs_commit"] == "51ad1231a231ee85234c06db807688d029b85c35"
    assert len(evidence["validation_fingerprint"]) == 64
    assert set(evidence["binaries"]) == {"openroad", "yosys", "klayout"}
