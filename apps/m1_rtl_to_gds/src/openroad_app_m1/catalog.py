"""The ten bounded Course Lab records and their initial PDK capabilities."""

from __future__ import annotations

from openroad_platform_contracts import (
    CapabilityStatus,
    CourseExercise,
    CourseLabRecord,
    PdkCapability,
)


_COURSES = (
    ("course-mux-decoder", "Mux / Decoder", "combinational", "intro"),
    ("course-priority-encoder", "Priority Encoder", "combinational", "intro"),
    ("course-adder-subtractor", "Adder / Subtractor", "arithmetic", "intro"),
    ("course-alu", "ALU", "datapath", "intermediate"),
    ("course-edge-detector", "Edge Detector", "sequential", "intro"),
    ("course-counter", "8-bit Synchronous Counter", "sequential", "intro"),
    ("course-shift-register", "Shift Register", "sequential", "intro"),
    ("course-fifo", "FIFO", "handshake", "intermediate"),
    ("course-uart-tx", "UART TX", "protocol", "intermediate"),
    ("course-sequence-fsm", "Sequence Detector / FSM", "fsm", "intermediate"),
)


def course_records() -> tuple[CourseLabRecord, ...]:
    return tuple(
        CourseLabRecord(
            exercise=CourseExercise(
                exercise_id=exercise_id,
                title=title,
                category=category,
                level=level,
                description=f"Frozen {title} exercise for the Agentic RTL-to-GDS course.",
                supported_pdks=("nangate45", "sky130hd", "asap7"),
                verification_id=f"{exercise_id}-verification-v1",
            ),
            spec_ref=f"spec:{exercise_id}-v1",
            reference_rtl_ref=f"source:{exercise_id}-reference-v1",
            oracle_ref=f"source:{exercise_id}-oracle-v1",
            recipe_id=f"{exercise_id}-nangate45-v1",
            teaching_notes=f"Teach {title} through a frozen specification, verification and evidence chain.",
        )
        for exercise_id, title, category, level in _COURSES
    )


def pdk_capabilities() -> tuple[PdkCapability, ...]:
    capabilities: list[PdkCapability] = []
    for record in course_records():
        for pdk in ("nangate45", "sky130hd", "asap7"):
            status = CapabilityStatus.REGISTERED
            reason = None
            if pdk != "nangate45":
                status = CapabilityStatus.BLOCKED
                reason = "PDK smoke is not complete in the first M1 release."
            capabilities.append(PdkCapability(
                exercise_id=record.exercise.exercise_id,
                pdk_id=pdk,
                status=status,
                recipe_id=record.recipe_id if pdk == "nangate45"
                else f"{record.exercise.exercise_id}-{pdk}-v1",
                reason=reason,
            ))
    return tuple(capabilities)
