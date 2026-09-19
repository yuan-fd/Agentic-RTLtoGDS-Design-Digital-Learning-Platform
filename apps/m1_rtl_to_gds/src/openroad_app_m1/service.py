"""M1 use cases and fail-closed state transitions."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace
from typing import Any

from openroad_platform_contracts.rtl_frontend import SpecIR, VerificationPackage
from openroad_platform_contracts.evidence_exchange import EvidenceRef

from .models import M1Session, M1State, RTLVersion, SimulationStatus, VerificationStatus
from .store import M1Store


class M1Service:
    def __init__(self, store: M1Store) -> None:
        self.store = store
        self._sessions = {
            session.spec_id: session
            for session in (M1Session.from_dict(json.loads(payload))
                            for payload in store.all_session_payloads())
        }
        self._versions = {
            version.version_id: version
            for version in (RTLVersion.from_dict(json.loads(payload))
                            for payload in store.all_version_payloads())
        }
        self._verification_packages = {
            package.spec_id: package
            for package in (VerificationPackage.from_dict(json.loads(payload))
                            for payload in store.all_verification_package_payloads())
        }
        self._evidence = {
            evidence.evidence_id: evidence
            for evidence in (EvidenceRef.from_dict(json.loads(payload))
                             for payload in store.all_evidence_payloads())
        }

    @classmethod
    def in_memory(cls) -> "M1Service":
        return cls(M1Store())

    @classmethod
    def open(cls, database: str) -> "M1Service":
        if not database or database == ":memory:":
            raise ValueError("a persistent M1 database path is required")
        return cls(M1Store(database))

    def assess_spec(
        self,
        owner_id: str,
        *,
        spec: SpecIR | None = None,
        clarification_questions: tuple[str, ...] = (),
        unsupported_reason: str | None = None,
    ) -> M1Session:
        if spec is not None and (clarification_questions or unsupported_reason):
            raise ValueError("spec, clarification questions, and unsupported scope are exclusive")
        if unsupported_reason:
            state = M1State.UNSUPPORTED_SCOPE
        elif clarification_questions or spec is None:
            state = M1State.NEEDS_CLARIFICATION
            if not clarification_questions:
                clarification_questions = ("Provide an executable clock, reset, port, and acceptance definition.",)
        else:
            spec.validate()
            questions = _clarification_questions(spec)
            if questions:
                state = M1State.NEEDS_CLARIFICATION
                clarification_questions = questions
            else:
                state = M1State.SPECIFIED
        session = M1Session(
            spec_id=f"spec-{uuid.uuid4().hex}", owner_id=owner_id, state=state,
            spec=spec, clarification_questions=clarification_questions,
            unsupported_reason=unsupported_reason,
        )
        session.validate()
        self._sessions[session.spec_id] = session
        self._save_session(session)
        return session

    def freeze_spec(self, spec_id: str) -> M1Session:
        session = self._session(spec_id)
        if session.state is M1State.UNSUPPORTED_SCOPE:
            raise ValueError("unsupported_scope cannot be frozen")
        if session.state is M1State.NEEDS_CLARIFICATION:
            raise ValueError("spec requires clarification before it can be frozen")
        if session.state is not M1State.SPECIFIED or session.spec is None:
            raise ValueError("spec is not ready to be frozen")
        frozen = replace(session, state=M1State.FROZEN, frozen_fingerprint=session.spec.fingerprint)
        frozen.validate()
        self._sessions[spec_id] = frozen
        self._save_session(frozen)
        return frozen

    def create_rtl_version(
        self, spec_id: str, rtl_source: str, generator: str, *,
        parent_version_id: str | None = None, source_ref: str | None = None,
    ) -> RTLVersion:
        session = self._session(spec_id)
        if session.state is not M1State.FROZEN:
            raise ValueError("RTL requires a frozen spec")
        if not isinstance(rtl_source, str) or not rtl_source.strip():
            raise ValueError("RTL source must be non-empty")
        if parent_version_id is not None:
            parent = self.get_rtl_version(parent_version_id)
            if parent.spec_id != spec_id:
                raise ValueError("RTL parent belongs to another spec")
            self._versions[parent.version_id] = replace(
                parent, verification_status=VerificationStatus.INVALIDATED,
                verification_run_id=None, simulation_status=SimulationStatus.INVALIDATED,
                simulation_run_id=None,
            )
            self._save_version(self._versions[parent.version_id])
        version = RTLVersion(
            version_id=f"rtl-{uuid.uuid4().hex}", spec_id=spec_id,
            rtl_sha256=hashlib.sha256(rtl_source.encode("utf-8")).hexdigest(),
            generator=generator, parent_version_id=parent_version_id,
            source_ref=source_ref,
        )
        version.validate()
        self._versions[version.version_id] = version
        self._save_version(version)
        return version

    def create_rtl_version_from_v2(
        self, spec_id: str, rtl_source: str, generator: str, v2_client: Any,
        *, parent_version_id: str | None = None,
    ) -> RTLVersion:
        input_record = v2_client.upload_rtl(rtl_source)
        input_id = input_record.get("input_id")
        if not isinstance(input_id, str) or not input_id:
            raise ValueError("v2 input upload did not return input_id")
        return self.create_rtl_version(
            spec_id, rtl_source, generator, parent_version_id=parent_version_id,
            source_ref=f"input:{input_id}",
        )

    def record_verification(
        self, version_id: str, status: VerificationStatus, run_id: str
    ) -> RTLVersion:
        version = self.get_rtl_version(version_id)
        if version.verification_status is VerificationStatus.INVALIDATED:
            raise ValueError("cannot record verification for an invalidated RTL version")
        if status not in {VerificationStatus.PASSED, VerificationStatus.FAILED}:
            raise ValueError("verification result must be passed or failed")
        updated = replace(version, verification_status=status, verification_run_id=run_id)
        updated.validate()
        self._versions[version_id] = updated
        self._save_version(updated)
        return updated

    def record_simulation(
        self, version_id: str, status: SimulationStatus, run_id: str
    ) -> RTLVersion:
        version = self.get_rtl_version(version_id)
        if version.verification_status is not VerificationStatus.PASSED:
            raise ValueError("cannot record simulation before verification passes")
        if status not in {SimulationStatus.PASSED, SimulationStatus.FAILED}:
            raise ValueError("simulation result must be passed or failed")
        updated = replace(version, simulation_status=status, simulation_run_id=run_id)
        updated.validate()
        self._versions[version_id] = updated
        self._save_version(updated)
        return updated

    def register_verification_package(
        self, spec_id: str, package: VerificationPackage
    ) -> VerificationPackage:
        session = self._session(spec_id)
        if session.state is not M1State.FROZEN:
            raise ValueError("VerificationPackage requires a frozen spec")
        if package.spec_id != spec_id:
            raise ValueError("VerificationPackage belongs to another spec")
        package.validate()
        if spec_id in self._verification_packages:
            raise ValueError("VerificationPackage is already frozen for this spec")
        self._verification_packages[spec_id] = package
        self.store.put_verification_package(
            package, json.dumps(package.to_dict(), sort_keys=True)
        )
        return package

    def build_verification_request(self, version_id: str, v2_client: Any) -> dict[str, Any]:
        version = self.get_rtl_version(version_id)
        session = self._session(version.spec_id)
        if session.state is not M1State.FROZEN or session.spec is None:
            raise ValueError("verification requires a frozen spec")
        if not version.source_ref:
            raise ValueError("RTL source must be staged in v2 before verification")
        package = self._verification_packages.get(version.spec_id)
        if package is None:
            raise ValueError("verification requires a frozen VerificationPackage")
        admitted = any(
            item.get("plugin_id") == "rtl-verify"
            and item.get("admission") == "admitted"
            and item.get("executable") is True
            and "eda.rtl.verify" in (item.get("capabilities") or ())
            for item in v2_client.plugins()
        )
        if not admitted:
            raise ValueError("rtl-verify Toolkit is not admitted by v2")
        return {
            "schema_version": 3,
            "task_id": f"m1-verify-{version.version_id}",
            "project_id": "teaching-m1",
            "design_id": f"m1-{version.version_id}",
            "plugin_id": "rtl-verify",
            "inputs": {
                "rtl_path": f"rtl/{session.spec.top}.sv",
                "top": session.spec.top,
                "spec_id": version.spec_id,
                "verification_id": package.verification_id,
                "compile_checks": list(package.compile_checks),
            },
            "staged_inputs": [{
                "destination": f"rtl/{session.spec.top}.sv",
                "input_id": version.source_ref.removeprefix("input:"),
                "required": True,
            }],
            "expected_artifacts": ["rtl", "verification_report", "log"],
            "timeout_seconds": 600,
            "max_attempts": 1,
        }

    def build_simulation_request(self, version_id: str, v2_client: Any) -> dict[str, Any]:
        version = self.get_rtl_version(version_id)
        session = self._session(version.spec_id)
        package = self._verification_packages.get(version.spec_id)
        if session.state is not M1State.FROZEN or session.spec is None:
            raise ValueError("simulation requires a frozen spec")
        if version.verification_status is not VerificationStatus.PASSED:
            raise ValueError("simulation requires passed compile/lint verification")
        if not version.source_ref:
            raise ValueError("RTL source must be staged in v2 before simulation")
        if package is None:
            raise ValueError("simulation requires a frozen VerificationPackage")
        if len(package.simulation_oracle_refs) != 1:
            raise ValueError("simulation requires exactly one frozen oracle artifact")
        if not package.simulation_top:
            raise ValueError("simulation requires a frozen simulation_top")
        oracle_ref = package.simulation_oracle_refs[0]
        oracle_id = oracle_ref.removeprefix("artifact:")
        if not oracle_id:
            raise ValueError("simulation oracle artifact reference is empty")
        admitted = any(
            item.get("plugin_id") == "rtl-sim"
            and item.get("admission") == "admitted"
            and item.get("executable") is True
            and "eda.rtl.simulate" in (item.get("capabilities") or ())
            for item in v2_client.plugins()
        )
        if not admitted:
            raise ValueError("rtl-sim Toolkit is not admitted by v2")
        return {
            "schema_version": 3,
            "task_id": f"m1-sim-{version.version_id}",
            "project_id": "teaching-m1",
            "design_id": f"m1-{version.version_id}",
            "plugin_id": "rtl-sim",
            "inputs": {
                "rtl_path": f"rtl/{session.spec.top}.sv",
                "testbench_path": "verification/oracle.sv",
                "top": session.spec.top,
                "simulation_top": package.simulation_top,
                "spec_id": version.spec_id,
                "verification_id": package.verification_id,
            },
            "staged_inputs": [
                {"destination": f"rtl/{session.spec.top}.sv",
                 "input_id": version.source_ref.removeprefix("input:"), "required": True},
                {"destination": "verification/oracle.sv",
                 "artifact_id": oracle_id, "required": True},
            ],
            "expected_artifacts": ["simulation_report", "log"],
            "timeout_seconds": 600,
            "max_attempts": 1,
        }

    def submit_verification(self, version_id: str, v2_client: Any) -> str:
        task = self.build_verification_request(version_id, v2_client)
        return self._submit_task(task, v2_client)

    def submit_simulation(self, version_id: str, v2_client: Any) -> str:
        task = self.build_simulation_request(version_id, v2_client)
        return self._submit_task(task, v2_client)

    def submit_rtl_to_gds(self, version_id: str, pdk: str, v2_client: Any) -> str:
        task = self.build_rtl_to_gds_request(version_id, pdk, v2_client)
        return self._submit_task(task, v2_client)

    def build_rtl_to_gds_request(self, version_id: str, pdk: str, v2_client: Any) -> dict[str, Any]:
        version = self.get_rtl_version(version_id)
        if version.verification_status is not VerificationStatus.PASSED:
            raise ValueError("RTL-to-GDS requires passed verification")
        if not version.source_ref:
            raise ValueError("RTL source must be staged in v2 before submission")
        if pdk not in {"nangate45", "sky130hd", "asap7"}:
            raise ValueError(f"unsupported PDK: {pdk}")
        session = self._session(version.spec_id)
        if session.state is not M1State.FROZEN or session.spec is None:
            raise ValueError("RTL-to-GDS requires a frozen spec")
        package = self._verification_packages.get(version.spec_id)
        if package is None:
            raise ValueError("RTL-to-GDS requires a frozen VerificationPackage")
        if version.simulation_status is not SimulationStatus.PASSED:
            raise ValueError("RTL-to-GDS requires passed simulation")
        admitted = any(
            item.get("plugin_id") == "orfs"
            and item.get("admission") == "admitted"
            and item.get("executable") is True
            and "eda.rtl_to_gds" in (item.get("capabilities") or ())
            for item in v2_client.plugins()
        )
        if not admitted:
            raise ValueError("orfs Toolkit is not admitted by v2")
        return {
            "schema_version": 3,
            "task_id": f"m1-gds-{version.version_id}-{pdk}",
            "project_id": "teaching-m1",
            "design_id": f"m1-{version.version_id}-{pdk}",
            "plugin_id": "orfs",
            "inputs": {
                "spec_fingerprint": session.spec.fingerprint,
                "rtl_sha256": version.rtl_sha256,
                "verification_run_id": version.verification_run_id,
                "verification_id": package.verification_id,
                "rtl_path": f"rtl/{session.spec.top}.sv",
                "platform": pdk,
                "top": session.spec.top,
                "clock": session.spec.clock,
                "clock_period_ns": session.spec.constraints["clock_period_ns"]
                if session.spec.clock is not None else None,
                "target_stage": "finish",
            },
            "staged_inputs": [{
                "destination": f"rtl/{session.spec.top}.sv",
                "input_id": version.source_ref.removeprefix("input:"),
                "required": True,
            }],
            "parameters": {
                "pdk": pdk,
                "rtl_version_id": version.version_id,
                "top": session.spec.top,
            },
            "expected_artifacts": ["report", "gds", "def", "netlist", "odb"],
            "timeout_seconds": 3600,
            "max_attempts": 1,
        }

    def get_rtl_version(self, version_id: str) -> RTLVersion:
        try:
            return self._versions[version_id]
        except KeyError as exc:
            raise KeyError(f"unknown RTL version: {version_id}") from exc

    def list_rtl_versions(self, spec_id: str) -> tuple[RTLVersion, ...]:
        self._session(spec_id)
        return tuple(version for version in self._versions.values() if version.spec_id == spec_id)

    @staticmethod
    def _submit_task(task: dict[str, Any], v2_client: Any) -> str:
        reply = v2_client.submit(task, idempotency_key=task["task_id"])
        run = reply.get("run") if isinstance(reply, dict) else None
        run_id = run.get("run_id") if isinstance(run, dict) else None
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("v2 returned a submission without run_id")
        return run_id

    def get_session(self, spec_id: str) -> M1Session:
        return self._session(spec_id)

    def get_verification_package(self, spec_id: str) -> VerificationPackage:
        try:
            return self._verification_packages[spec_id]
        except KeyError as exc:
            raise KeyError(f"unknown VerificationPackage for spec: {spec_id}") from exc

    def record_evidence(self, evidence: EvidenceRef) -> EvidenceRef:
        evidence.validate()
        session = self._session(evidence.spec_id)
        version = self.get_rtl_version(evidence.candidate_id)
        if session.owner_id != evidence.owner_id:
            raise ValueError("evidence owner does not own the spec")
        if version.spec_id != evidence.spec_id:
            raise ValueError("evidence candidate belongs to another spec")
        if evidence.evidence_kind == "rtl_to_gds" and evidence.status == "succeeded":
            if not any(item.startswith("artifact:gds") for item in evidence.artifact_ids):
                raise ValueError("successful rtl_to_gds evidence requires artifact:gds")
            if version.verification_status is not VerificationStatus.PASSED:
                raise ValueError("successful GDS evidence requires passed RTL verification")
        if evidence.evidence_id in self._evidence:
            raise ValueError("evidence_id is already registered")
        self._evidence[evidence.evidence_id] = evidence
        self.store.put_evidence(evidence, json.dumps(evidence.to_dict(), sort_keys=True))
        return evidence

    def get_evidence(self, evidence_id: str) -> EvidenceRef:
        try:
            return self._evidence[evidence_id]
        except KeyError as exc:
            raise KeyError(f"unknown evidence: {evidence_id}") from exc

    def _session(self, spec_id: str) -> M1Session:
        try:
            return self._sessions[spec_id]
        except KeyError as exc:
            raise KeyError(f"unknown spec: {spec_id}") from exc

    def _save_session(self, session: M1Session) -> None:
        self.store.put_session(session, json.dumps(session.to_dict(), sort_keys=True))

    def _save_version(self, version: RTLVersion) -> None:
        self.store.put_version(version, json.dumps(version.to_dict(), sort_keys=True))


def _clarification_questions(spec: SpecIR) -> tuple[str, ...]:
    if spec.clock is None:
        return ()
    period = spec.constraints.get("clock_period_ns")
    if isinstance(period, bool) or not isinstance(period, (int, float)) or period <= 0:
        return ("What clock period in nanoseconds should the frozen recipe use?",)
    return ()
