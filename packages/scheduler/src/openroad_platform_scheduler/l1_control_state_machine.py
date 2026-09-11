"""Durable Planner/Analyzer/Debugger state transitions for L1.

The topology adapts PDAGENT's hub-and-spoke roles to platform governance:
Runtime replaces a shell-owning Worker, deterministic StageAnalysis replaces
free-form log condensation, and this coordinator can request only typed work.
It contains no EDA executor and no optimization algorithm.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from openroad_platform_contracts import (
    AnalyzerState, ConvergenceState, DebuggerState, DiagnosisReport,
    EvidencePointer, PlannerPhase, PlannerState, RecoveryAction, RecoveryDecision,
    ConvergenceAssessment,
    RecoveryBudget, RecoveryClass, RTLCheckpointRestorePlan,
)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _merge_evidence(*groups) -> tuple[EvidencePointer, ...]:
    return tuple(dict.fromkeys(item for group in groups for item in group))


class L1ControlStateStore:
    """Append-only SQLite checkpoints; Runtime remains execution authority."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS l1_planner_state ("
                "planner_state_id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, "
                "revision INTEGER NOT NULL, parent_state_id TEXT, payload_json TEXT NOT NULL, "
                "UNIQUE(goal_id, revision))")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS l1_analyzer_state ("
                "analyzer_state_id TEXT PRIMARY KEY, planner_state_id TEXT NOT NULL, "
                "payload_json TEXT NOT NULL)")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS l1_debugger_state ("
                "debugger_state_id TEXT PRIMARY KEY, planner_state_id TEXT NOT NULL, "
                "payload_json TEXT NOT NULL)")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS l1_recovery_decision ("
                "decision_id TEXT PRIMARY KEY, planner_state_id TEXT NOT NULL, "
                "payload_json TEXT NOT NULL)")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS l1_rtl_restore_plan ("
                "plan_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, "
                "payload_json TEXT NOT NULL)")

    @staticmethod
    def _json(value: dict) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def append_planner(self, state: PlannerState) -> None:
        state.validate()
        with sqlite3.connect(self.database) as connection:
            if state.parent_state_id is None:
                existing = connection.execute(
                    "SELECT 1 FROM l1_planner_state WHERE goal_id=?", (state.goal_id,)
                ).fetchone()
                if state.revision != 0 or existing is not None:
                    raise ValueError("initial planner state must be the first goal revision")
            else:
                parent = connection.execute(
                    "SELECT goal_id,revision FROM l1_planner_state WHERE planner_state_id=?",
                    (state.parent_state_id,),
                ).fetchone()
                if parent != (state.goal_id, state.revision - 1):
                    raise ValueError("planner state lineage is invalid")
            connection.execute(
                "INSERT INTO l1_planner_state VALUES(?,?,?,?,?)",
                (state.planner_state_id, state.goal_id, state.revision,
                 state.parent_state_id, self._json(state.to_dict())),
            )

    def get_planner(self, state_id: str) -> PlannerState:
        with sqlite3.connect(self.database) as connection:
            row = connection.execute(
                "SELECT payload_json FROM l1_planner_state WHERE planner_state_id=?",
                (state_id,),
            ).fetchone()
        if row is None:
            raise KeyError(state_id)
        return PlannerState.from_dict(json.loads(row[0]))

    def latest(self, goal_id: str) -> PlannerState:
        with sqlite3.connect(self.database) as connection:
            row = connection.execute(
                "SELECT payload_json FROM l1_planner_state WHERE goal_id=? "
                "ORDER BY revision DESC LIMIT 1", (goal_id,),
            ).fetchone()
        if row is None:
            raise KeyError(goal_id)
        return PlannerState.from_dict(json.loads(row[0]))

    def append_analyzer(self, state: AnalyzerState) -> None:
        state.validate()
        self.get_planner(state.planner_state_id)
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO l1_analyzer_state VALUES(?,?,?)",
                (state.analyzer_state_id, state.planner_state_id,
                 self._json(state.to_dict())),
            )

    def append_debugger(self, state: DebuggerState) -> None:
        state.validate()
        self.get_planner(state.planner_state_id)
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO l1_debugger_state VALUES(?,?,?)",
                (state.debugger_state_id, state.planner_state_id,
                 self._json(state.to_dict())),
            )

    def append_recovery_decision(self, decision: RecoveryDecision) -> None:
        decision.validate()
        self.get_planner(decision.planner_state_id)
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO l1_recovery_decision VALUES(?,?,?)",
                (decision.decision_id, decision.planner_state_id,
                 self._json(decision.to_dict())),
            )

    def get_recovery_decision(self, decision_id: str) -> RecoveryDecision:
        with sqlite3.connect(self.database) as connection:
            row = connection.execute(
                "SELECT payload_json FROM l1_recovery_decision WHERE decision_id=?",
                (decision_id,),
            ).fetchone()
        if row is None:
            raise KeyError(decision_id)
        return RecoveryDecision.from_dict(json.loads(row[0]))

    def append_rtl_restore_plan(self, plan: RTLCheckpointRestorePlan) -> None:
        plan.validate()
        self.get_recovery_decision(plan.recovery_decision_id)
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO l1_rtl_restore_plan VALUES(?,?,?)",
                (plan.plan_id, plan.recovery_decision_id,
                 self._json(plan.to_dict())),
            )

    def get_rtl_restore_plan(self, plan_id: str) -> RTLCheckpointRestorePlan:
        with sqlite3.connect(self.database) as connection:
            row = connection.execute(
                "SELECT payload_json FROM l1_rtl_restore_plan WHERE plan_id=?",
                (plan_id,),
            ).fetchone()
        if row is None:
            raise KeyError(plan_id)
        return RTLCheckpointRestorePlan.from_dict(json.loads(row[0]))


class PDAgentControlStateMachine:
    """Strict role transitions; callers persist each returned checkpoint."""

    @staticmethod
    def initialize(goal_id: str, stage_plan: tuple[str, ...],
                   evidence: tuple[EvidencePointer, ...], *,
                   recovery_budget: RecoveryBudget | None = None) -> PlannerState:
        state = PlannerState(
            _id("planner"), goal_id, 0, PlannerPhase.PLANNING, stage_plan, 0,
            ConvergenceState.UNKNOWN, recovery_budget or RecoveryBudget(), evidence,
        )
        state.validate()
        return state

    @staticmethod
    def runtime_submitted(state: PlannerState, *, run_id: str,
                          evidence: tuple[EvidencePointer, ...]) -> PlannerState:
        state.validate()
        if state.phase is not PlannerPhase.PLANNING or state.current_stage is None:
            raise ValueError("Runtime submission requires an active planning stage")
        successor = replace(
            state, planner_state_id=_id("planner"), revision=state.revision + 1,
            phase=PlannerPhase.AWAITING_RUNTIME, last_run_id=run_id,
            diagnosis_report_id=None, parent_state_id=state.planner_state_id,
            convergence=ConvergenceState.UNKNOWN,
            convergence_assessment_id=None,
            evidence=_merge_evidence(state.evidence, evidence),
        )
        successor.validate()
        return successor

    @staticmethod
    def record_convergence(state: PlannerState,
                           assessment: ConvergenceAssessment) -> PlannerState:
        state.validate(); assessment.validate()
        if state.phase not in {PlannerPhase.REVIEWING, PlannerPhase.DEBUGGING}:
            raise ValueError("convergence requires reviewed or debugging analysis")
        successor = replace(
            state, planner_state_id=_id("planner"), revision=state.revision + 1,
            convergence=assessment.state,
            convergence_assessment_id=assessment.assessment_id,
            parent_state_id=state.planner_state_id,
            evidence=_merge_evidence(state.evidence, assessment.evidence),
        )
        successor.validate()
        return successor

    @staticmethod
    def runtime_terminal(state: PlannerState, *, terminal_status: str,
                         evidence: tuple[EvidencePointer, ...]) -> PlannerState:
        state.validate()
        if state.phase is not PlannerPhase.AWAITING_RUNTIME:
            raise ValueError("terminal Runtime fact requires awaiting_runtime")
        if terminal_status not in {"succeeded", "failed", "cancelled", "timed_out", "lost"}:
            raise ValueError("Runtime terminal status is invalid")
        successor = replace(
            state, planner_state_id=_id("planner"), revision=state.revision + 1,
            phase=PlannerPhase.ANALYZING, parent_state_id=state.planner_state_id,
            evidence=_merge_evidence(state.evidence, evidence),
        )
        successor.validate()
        return successor

    @staticmethod
    def analysis_completed(state: PlannerState, report: DiagnosisReport) -> tuple[
            PlannerState, AnalyzerState, DebuggerState | None]:
        state.validate(); report.validate()
        if state.phase is not PlannerPhase.ANALYZING:
            raise ValueError("DiagnosisReport requires an analyzing planner")
        if report.run_id != state.last_run_id:
            raise ValueError("DiagnosisReport does not bind the active Runtime run")
        phase = PlannerPhase.DEBUGGING if report.blockers else PlannerPhase.REVIEWING
        successor = replace(
            state, planner_state_id=_id("planner"), revision=state.revision + 1,
            phase=phase, diagnosis_report_id=report.report_id,
            parent_state_id=state.planner_state_id,
            evidence=_merge_evidence(state.evidence, report.evidence),
        )
        successor.validate()
        analyzer = AnalyzerState(
            _id("analyzer"), state.planner_state_id, report.run_id, "completed",
            tuple(item.analysis_id for item in report.analyses), report.evidence,
            report.report_id,
        )
        analyzer.validate()
        debugger = None
        if report.blockers:
            facts = tuple(fact.fact_id for analysis in report.analyses
                          for fact in analysis.facts)
            debugger = DebuggerState(
                _id("debugger"), successor.planner_state_id, report.report_id,
                "investigating", report.blockers, facts, report.evidence,
            )
            debugger.validate()
        return successor, analyzer, debugger

    @staticmethod
    def review_advance(state: PlannerState) -> PlannerState:
        state.validate()
        if state.phase is not PlannerPhase.REVIEWING:
            raise ValueError("stage advance requires a reviewed clean analysis")
        next_index = state.stage_index + 1
        phase = (PlannerPhase.COMPLETED if next_index == len(state.stage_plan)
                 else PlannerPhase.PLANNING)
        successor = replace(
            state, planner_state_id=_id("planner"), revision=state.revision + 1,
            phase=phase, stage_index=next_index,
            last_run_id=None if phase is PlannerPhase.PLANNING else state.last_run_id,
            diagnosis_report_id=None if phase is PlannerPhase.PLANNING else state.diagnosis_report_id,
            parent_state_id=state.planner_state_id,
        )
        successor.validate()
        return successor

    @staticmethod
    def propose_debug_action(state: PlannerState, debugger: DebuggerState,
                             *, action: RecoveryAction,
                             recovery_class: RecoveryClass | None = None) -> tuple[
                                 PlannerState, DebuggerState]:
        state.validate(); debugger.validate()
        if (state.phase is not PlannerPhase.DEBUGGING
                or debugger.status != "investigating"
                or debugger.planner_state_id != state.planner_state_id
                or debugger.diagnosis_report_id != state.diagnosis_report_id):
            raise ValueError("debugger does not bind the active planner diagnosis")
        required = {
            RecoveryAction.RETRY: RecoveryClass.MICRO,
            RecoveryAction.REQUEST_TYPED_FIX: RecoveryClass.MESO,
            RecoveryAction.ROLLBACK: RecoveryClass.MACRO,
        }.get(action)
        budget = state.recovery_budget
        if required is not None:
            if recovery_class is not required:
                raise ValueError("recovery action does not match its budget class")
            budget = budget.consume(required)
        elif recovery_class is not None:
            raise ValueError("this action does not consume a recovery budget")
        phase = {
            RecoveryAction.CONTINUE: PlannerPhase.PLANNING,
            RecoveryAction.RETRY: PlannerPhase.PLANNING,
            RecoveryAction.REQUEST_TYPED_FIX: PlannerPhase.PLANNING,
            RecoveryAction.ROLLBACK: PlannerPhase.ROLLBACK_PENDING,
            RecoveryAction.SKIP: PlannerPhase.PLANNING,
            RecoveryAction.ESCALATE_L2: PlannerPhase.ESCALATED,
            RecoveryAction.STOP: PlannerPhase.FAILED,
        }[action]
        stage_index = state.stage_index + 1 if action is RecoveryAction.SKIP else state.stage_index
        if stage_index == len(state.stage_plan):
            phase = PlannerPhase.COMPLETED
        proposed = replace(
            debugger, debugger_state_id=_id("debugger"),
            status="action_proposed", proposed_action=action,
            recovery_class=recovery_class,
        )
        proposed.validate()
        successor = replace(
            state, planner_state_id=_id("planner"), revision=state.revision + 1,
            phase=phase, stage_index=stage_index, recovery_budget=budget,
            parent_state_id=state.planner_state_id,
            last_run_id=(state.last_run_id if phase in {
                PlannerPhase.ROLLBACK_PENDING, PlannerPhase.ESCALATED,
                PlannerPhase.FAILED, PlannerPhase.COMPLETED} else None),
            diagnosis_report_id=(state.diagnosis_report_id if phase in {
                PlannerPhase.ROLLBACK_PENDING, PlannerPhase.ESCALATED,
                PlannerPhase.FAILED, PlannerPhase.COMPLETED} else None),
        )
        successor.validate()
        return successor, proposed
