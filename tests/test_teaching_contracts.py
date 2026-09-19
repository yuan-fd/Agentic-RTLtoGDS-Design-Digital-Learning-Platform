from __future__ import annotations

import pytest

from openroad_platform_contracts.evidence_exchange import EvidenceRef
from openroad_platform_contracts.teaching_catalog import (
    CapabilityStatus,
    CourseExercise,
    PdkCapability,
    ScriptProposal,
)


def test_course_exercise_requires_a_real_catalog_identity() -> None:
    exercise = CourseExercise(
        exercise_id="course-counter",
        title="Counter",
        category="sequential",
        level="intermediate",
        description="A synchronous counter with reset and enable.",
        supported_pdks=("nangate45", "sky130hd", "asap7"),
        verification_id="oracle-course-counter-v1",
    )

    assert exercise.to_dict()["exercise_id"] == "course-counter"
    assert exercise.supported_pdks == ("nangate45", "sky130hd", "asap7")


def test_pdk_capability_does_not_claim_available_before_gds_smoke() -> None:
    capability = PdkCapability(
        exercise_id="course-counter",
        pdk_id="nangate45",
        status=CapabilityStatus.GDS_SMOKE_PASSED,
        recipe_id="course-counter-nangate45-v1",
        reason="Real bounded finish smoke completed.",
        smoke_evidence_id="evidence:counter-nangate45-smoke",
    )

    assert capability.available is True
    assert capability.to_dict()["status"] == "gds_smoke_passed"


def test_pdk_capability_reports_blocked_without_falling_back_to_another_pdk() -> None:
    capability = PdkCapability(
        exercise_id="course-counter",
        pdk_id="asap7",
        status=CapabilityStatus.BLOCKED,
        recipe_id="course-counter-asap7-v1",
        reason="KLayout is not installed on this worker.",
    )

    assert capability.available is False
    assert capability.to_dict()["pdk_id"] == "asap7"


def test_evidence_ref_requires_hash_bound_artifacts() -> None:
    evidence = EvidenceRef(
        evidence_id="evidence:run-1",
        owner_id="user-1",
        spec_id="spec-counter",
        candidate_id="rtl-counter-v2",
        run_id="run-1",
        artifact_ids=("artifact:gds-1", "artifact:report-1"),
        evidence_kind="rtl_to_gds",
        status="succeeded",
        sha256="a" * 64,
        toolchain_digest="b" * 64,
        protocol_digest="c" * 64,
        claim_boundary="Measured artifacts from one bounded ORFS run.",
        created_at="2026-09-19T00:00:00Z",
    )

    assert evidence.complete is True
    assert evidence.to_dict()["artifact_ids"] == ["artifact:gds-1", "artifact:report-1"]


def test_script_proposal_rejects_absolute_and_parent_paths() -> None:
    with pytest.raises(ValueError, match="relative allowed path"):
        ScriptProposal(
            proposal_id="proposal-1",
            owner_id="user-1",
            entrypoint_id="orfs.recipe.v1",
            base_recipe_digest="a" * 64,
            patch="--- a/flow/config.mk\n+++ b/flow/config.mk\n",
            allowed_paths=("/etc/passwd",),
            requires_confirmation=True,
        ).validate()

    with pytest.raises(ValueError, match="relative allowed path"):
        ScriptProposal(
            proposal_id="proposal-2",
            owner_id="user-1",
            entrypoint_id="orfs.recipe.v1",
            base_recipe_digest="a" * 64,
            patch="--- a/flow/config.mk\n+++ b/flow/config.mk\n",
            allowed_paths=("../flow/config.mk",),
            requires_confirmation=True,
        ).validate()


def test_script_proposal_must_require_explicit_confirmation() -> None:
    with pytest.raises(ValueError, match="confirmation"):
        ScriptProposal(
            proposal_id="proposal-3",
            owner_id="user-1",
            entrypoint_id="orfs.recipe.v1",
            base_recipe_digest="a" * 64,
            patch="--- a/flow/config.mk\n+++ b/flow/config.mk\n",
            allowed_paths=("flow/config.mk",),
            requires_confirmation=False,
        ).validate()
