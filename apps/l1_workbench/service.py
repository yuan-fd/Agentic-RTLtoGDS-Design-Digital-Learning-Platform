"""Operational L1 vertical slice; transport/UI are deliberately absent."""
from __future__ import annotations
import json, platform, sqlite3, sys, uuid, threading, hashlib
from pathlib import Path
from dataclasses import replace
from typing import Any

from openroad_platform_contracts import PluginManifest, RTLToGDSRequest, TaskSpec, validate_teaching_mode
from openroad_platform_contracts.agent_control import DEFAULT_L1_TOOLS, AgentBudget, DesignState, GoalPreference, QoRConstraint, SemanticToolCall, ToolName
from openroad_platform_contracts.l1_goal_draft import ClarificationAnswer, ClarificationField, ClarificationQuestion
from openroad_platform_contracts.l1_policy import TrustedPolicyIdentity
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_contracts.l2_optimization import L2HandoffAuthorization, OptimizationRequest
from openroad_platform_contracts.product_surface import DEFAULT_PRODUCT_SURFACE, ProductRole
from openroad_platform_execution import (ORAssistantKnowledgeTaskFactory, ORASSISTANT_CAPABILITY,
    A2ORFODomain, ORFSAgentFullDomain, ORFSRTLToGDSFactory, PluginRegistry,
    ProcessAdapter, ProcessGuardian, ToolchainConfig, orfs_agent_full_protocol_receipts, orfs_plugin_manifest,
    a2_orfo_plugin_manifest, load_orfs_agent_paper_reference_design,
)
from openroad_platform_execution.orfs_agent_plugin import orfs_agent_plugin_manifest
from openroad_platform_scheduler.l1_goal_finalizer import TrustedGoalPolicy
from openroad_platform_scheduler.l1_loop import L1DurableLoop
from openroad_platform_scheduler.l1_loop_store import L1LoopStore
from openroad_platform_scheduler.l1_runtime_bridge import L1RuntimeBridge
from openroad_platform_scheduler.l1_session_service import L1SessionService, L1SessionStore
from openroad_platform_scheduler.l1_trace_service import L1TraceService
from openroad_platform_scheduler.l1_trace_store import L1TraceStore
from openroad_platform_scheduler.l1_l2_authorization import L1L2AuthorizationService
from openroad_platform_scheduler.l1_model_boundary import L1KnowledgeHit, L1ModelBoundary
from openroad_platform_scheduler.l2_handoff_store import L2HandoffStore
from openroad_platform_scheduler.l2_handoff import OptimizationHandoffService
from openroad_platform_scheduler.a2_orfo_campaign import (
    A2_ORFO_CAMPAIGN_KIND, A2ORFOCampaignService,
)
from openroad_platform_scheduler.pipeline_checkpoint import PipelineCheckpointStore
from openroad_platform_scheduler.runtime import WorkflowRuntime
from openroad_platform_scheduler.runtime_store import RuntimeStore
try:
    from .tutorial_profile import ManagedTutorialProfile
    from .tutorial_planner import TutorialEvidencePlanner
    from .tutorial_semantic import MuxHandsOnSemanticProvider
    from .m1_planner import M1EvidencePlanner
    from .codex_goal_provider import CodexGoalDraftProvider
    from .l2_campaign_evidence import ORFSAgentCampaignEvidence
    from .teaching import teaching_replay
except ImportError:  # Direct ``python apps/l1_workbench/server.py`` launch.
    from tutorial_profile import ManagedTutorialProfile
    from tutorial_planner import TutorialEvidencePlanner
    from tutorial_semantic import MuxHandsOnSemanticProvider
    from m1_planner import M1EvidencePlanner
    from codex_goal_provider import CodexGoalDraftProvider
    from l2_campaign_evidence import ORFSAgentCampaignEvidence
    from teaching import teaching_replay

class _Provider:
    provider_id = "l1-workbench-deterministic-v1"
    def __init__(self, questions=()): self.questions=tuple(questions)
    def complete(self, request):
        if request["kind"] == "goal_draft":
            return {"schema_version":1,"request_text": request["request_text"], "intent": "execute", "answers": [], "questions": request["required_questions"]}
        prior=request["prior_draft"]; return {"schema_version":1,"request_text":prior["request_text"],"intent":"execute","questions":prior["questions"],"answers":request["answers"]}

class WorkbenchService:
    """L1 composition root; ``orfs`` binds its typed loop to real EDA."""
    def __init__(self, root: str | Path, *, backend="smoke", rtl=None,
                 top="mux_2to1", platform_name="nangate45", clock_period_ns=10.0,
                 orfs_agent_source: str | Path | None = None,
                 design_id: str | None = None,
                 orfs_agent_paper_orfs: str | Path | None = None,
                 orfs_agent_openroad_bin: str | Path | None = None,
                 orfs_agent_yosys_bin: str | Path | None = None,
                 orfs_agent_paper_environment: dict[str, str] | None = None,
                 a2_orfo_source: str | Path | None = None,
                 a2_orfo_model: str | Path | None = None,
                 a2_orfo_python: str | Path | None = None,
                 a2_orfo_codex: str | Path | None = None,
                 l2_protocol_budget: dict[str, int] | None = None,
                 l2_max_parallel: int = 4,
                 model_provider="tutorial",
                 managed_reference: str | None = None):
        if model_provider not in {"tutorial", "codex"}:
            raise ValueError("model_provider must be tutorial or codex")
        self.model_provider = model_provider
        self._teaching_modes: dict[str, str] = {}
        self._codex_provider = None
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        repository = Path(__file__).resolve().parents[2]
        if backend not in {"smoke", "orfs"}: raise ValueError("backend must be smoke or orfs")
        self.backend = backend
        self.managed_reference = managed_reference
        self.reference_design = None
        self.trace=L1TraceService(L1TraceStore(self.root/"trace.sqlite"))
        self.orfs_agent_source = Path(orfs_agent_source).expanduser().resolve() if orfs_agent_source else None
        self.orfs_agent_paper_orfs = (Path(orfs_agent_paper_orfs).expanduser().resolve()
                                      if orfs_agent_paper_orfs else None)
        self.orfs_agent_openroad_bin = (Path(orfs_agent_openroad_bin).expanduser().resolve()
                                        if orfs_agent_openroad_bin else None)
        self.orfs_agent_yosys_bin = (Path(orfs_agent_yosys_bin).expanduser().resolve()
                                     if orfs_agent_yosys_bin else None)
        self.orfs_agent_paper_environment = dict(orfs_agent_paper_environment or {})
        default_a2_source = repository / "var/external-sources/a2-orfo-8b20a3c-clean"
        default_a2_model = repository / "var/external-models/mxbai-embed-large-v1-b33106f"
        default_a2_python = repository / ".tools/venvs/a2-orfo/bin/python"
        self.a2_orfo_source = Path(
            a2_orfo_source or default_a2_source).expanduser().resolve()
        self.a2_orfo_model = Path(
            a2_orfo_model or default_a2_model).expanduser().resolve()
        self.a2_orfo_python = Path(
            a2_orfo_python or default_a2_python).expanduser().resolve()
        self.a2_orfo_codex = (Path(a2_orfo_codex).expanduser().resolve()
                              if a2_orfo_codex else None)
        if managed_reference is not None:
            if managed_reference != "orfs-agent-paper-aes-sky130hd":
                raise ValueError("unknown managed L1 reference design")
            if backend != "orfs":
                raise ValueError("managed L1 reference design requires the real ORFS backend")
            if rtl is not None:
                raise ValueError("managed L1 reference design cannot be combined with --rtl")
            if not all((self.orfs_agent_paper_orfs, self.orfs_agent_openroad_bin,
                        self.orfs_agent_yosys_bin)):
                raise ValueError("managed L1 reference requires the complete paper toolchain")
            self.reference_design = load_orfs_agent_paper_reference_design(
                self.orfs_agent_paper_orfs)
            if design_id not in {None, self.reference_design.design}:
                raise ValueError("managed L1 reference design_id is operator-owned")
            self.rtl = next(path for path in self.reference_design.rtl_files
                            if path.stem == self.reference_design.top)
            self.top = self.reference_design.top
            self.platform_name = self.reference_design.platform
            self.clock_period_ns = self.reference_design.clock_period_ns
            self.design_id = self.reference_design.design
        else:
            self.rtl = Path(rtl).expanduser().resolve() if rtl else None
            self.top = top
            self.platform_name, self.clock_period_ns = platform_name, clock_period_ns
            self.design_id = design_id or top
        self.l2_protocol_budget = dict(l2_protocol_budget or {
            # Pinned A2-ORFO launcher: iteration 1 has 25 perturbed points plus
            # one default; five feedback iterations each execute 25 points.
            "initial_samples": 26, "feedback_steps": 5,
            "suggestions_per_step": 25, "confirmations": 0,
        })
        if (set(self.l2_protocol_budget) != {
                "initial_samples", "feedback_steps", "suggestions_per_step", "confirmations"}
                or any(isinstance(value, bool) or not isinstance(value, int) or value < 0
                       for value in self.l2_protocol_budget.values())
                or min(self.l2_protocol_budget["initial_samples"],
                       self.l2_protocol_budget["feedback_steps"],
                       self.l2_protocol_budget["suggestions_per_step"]) < 1):
            raise ValueError("L2 protocol budget must define the complete A2 campaign shape")
        if (isinstance(l2_max_parallel, bool) or not isinstance(l2_max_parallel, int)
                or not 1 <= l2_max_parallel <= 64):
            raise ValueError("L2 max_parallel must be an integer between 1 and 64")
        self.l2_max_parallel = l2_max_parallel
        protected_evaluator = None
        if backend == "orfs":
            from openroad_platform_analysis import ORFSProtectedEvaluator
            if self.rtl is None or not self.rtl.is_file(): raise FileNotFoundError("ORFS workbench requires frozen RTL")
            if self.reference_design is not None:
                self.toolchain = ToolchainConfig(
                    name="orfs-ce8d36a-paper-l1",
                    orfs_root=self.orfs_agent_paper_orfs,
                    openroad_bin=self.orfs_agent_openroad_bin,
                    yosys_bin=self.orfs_agent_yosys_bin,
                    klayout_bin=None,
                    environment=self.orfs_agent_paper_environment,
                )
            else:
                self.toolchain=ToolchainConfig.from_environment(name="orfs-2d-baseline")
            self.toolchain.validate()
            self.factory=ORFSRTLToGDSFactory(); manifest=orfs_plugin_manifest(self.toolchain, default_timeout_seconds=7200)
            protected_evaluator=ORFSProtectedEvaluator()
        else:
            self.toolchain=None; self.factory=None
            manifest=PluginManifest("l1-runtime-smoke","1",(sys.executable,str(Path(__file__).with_name("runtime_adapter.py"))),("eda.rtl_to_gds",),(platform.machine(),),{"type":"object"},{"type":"object"},({"kind":"report","required":True},),30)
        self.profile = (ManagedTutorialProfile(
            profile_id="orfs_agent_paper_aes_sky130hd_l1_v1",
            design_context="managed_aes_sky130hd_4p5ns_paper_baseline",
            design_label="managed_aes_sky130hd_reference",
        ) if self.reference_design is not None else
            ManagedTutorialProfile() if backend == "orfs" else None)
        self.required_goal_questions = (self.profile.questions() if self.profile else (
            ClarificationQuestion(
                "objective-1", ClarificationField.OBJECTIVE,
                "Confirm this bounded Runtime tool execution.", True,
            ),
        ))
        self.sessions=L1SessionService(L1SessionStore(self.root/"sessions.sqlite"),self.trace,
                                       goal_finalizer=self.profile.compile if self.profile else None)
        manifests = [manifest]
        self.knowledge_factory = None
        orassistant_inputs = (
            repository / "var/external-envs/orassistant-retrieval-a5df2dfe/bin/python",
            repository / "var/external-sources/orassistant-a5df2dfe-clean",
            repository / "var/external-sources/openroad-docs-63ed2e0-clean",
            repository / "integrations/orassistant/orassistant.plugin.json",
        )
        if all(path.exists() for path in orassistant_inputs):
            knowledge_registry = PluginRegistry.from_directory(
                repository / "integrations/orassistant")
            knowledge_manifest = knowledge_registry.resolve(
                "orassistant", capability=ORASSISTANT_CAPABILITY)
            DEFAULT_PRODUCT_SURFACE.authorize(
                ProductRole.OPENROAD_KNOWLEDGE, knowledge_manifest)
            manifests.append(knowledge_manifest)
            self.knowledge_factory = ORAssistantKnowledgeTaskFactory()
        if self.orfs_agent_source:
            if backend != "orfs":
                raise ValueError("ORFS-Agent requires the real ORFS workbench backend")
            paper_values = (self.orfs_agent_paper_orfs, self.orfs_agent_openroad_bin,
                            self.orfs_agent_yosys_bin)
            if any(value is not None for value in paper_values) and not all(
                    value is not None for value in paper_values):
                raise ValueError("full L2 requires paper ORFS, OpenROAD, and Yosys together")
            if self.orfs_agent_paper_environment and not all(
                    value is not None for value in paper_values):
                raise ValueError("paper toolchain environment requires the complete full L2 toolchain")
            manifests.append(orfs_agent_plugin_manifest(
                self.orfs_agent_source,
                **({
                    "paper_orfs_root": self.orfs_agent_paper_orfs,
                    "openroad_bin": self.orfs_agent_openroad_bin,
                    "yosys_bin": self.orfs_agent_yosys_bin,
                    "paper_runtime_environment": self.orfs_agent_paper_environment,
                } if all(value is not None for value in paper_values) else {}),
            ))
            if not all(path.exists() for path in (
                    self.a2_orfo_source, self.a2_orfo_model,
                    self.a2_orfo_python)):
                raise ValueError("A2-ORFO product assets are not completely installed")
            manifests.append(a2_orfo_plugin_manifest(
                self.a2_orfo_source, model_root=self.a2_orfo_model,
                python_executable=self.a2_orfo_python,
                codex_executable=self.a2_orfo_codex,
                default_timeout_seconds=3600))
        self.runtime=WorkflowRuntime(RuntimeStore(self.root/"runtime.sqlite"),PluginRegistry(manifests),workspace_root=self.root/"work",adapter=ProcessAdapter(ProcessGuardian(poll_interval=.01,terminate_grace=.1)),protected_evaluator=protected_evaluator)
        self.loop_store=L1LoopStore(self.root/"loop.sqlite")
        self.l2_handoff_store=L2HandoffStore(self.root/"l2_handoff.sqlite")
        self.l2_checkpoints=PipelineCheckpointStore(self.root/"l2_campaign.sqlite")
        self.l2_evidence=ORFSAgentCampaignEvidence(self.runtime)
        self.l2_campaign=A2ORFOCampaignService(
            checkpoints=self.l2_checkpoints, runtime=self.runtime,
            runtime_store=self.runtime.store,
            observation_for_run=self.l2_evidence.observation_for_run,
            policy_result_for_run=self.l2_evidence.a2_policy_result_for_run,
        )
        with sqlite3.connect(self.root/"workbench.sqlite") as c: c.execute("CREATE TABLE IF NOT EXISTS session_state(session_id TEXT PRIMARY KEY,state_json TEXT,plan_id TEXT)")
    def policy(self):
        evidence=EvidencePointer("artifact:workbench-rtl","a"*64); provenance=EvidencePointer("artifact:workbench-policy","b"*64)
        allowed_tools = (DEFAULT_L1_TOOLS if self.knowledge_factory is not None else
                         tuple(tool for tool in DEFAULT_L1_TOOLS
                               if tool is not ToolName.QUERY_OPENROAD_KNOWLEDGE))
        if self.backend == "orfs":
            import hashlib
            digest=(self.reference_design.source_fingerprint
                    if self.reference_design is not None
                    else hashlib.sha256(self.rtl.read_bytes()).hexdigest())
            evidence_kind = "rtl-bundle" if self.reference_design is not None else "rtl"
            evidence=EvidencePointer(f"artifact:{evidence_kind}-{digest[:12]}",digest)
            return TrustedGoalPolicy("l1-orfs-baseline-policy","v1","platform",provenance,
                "l1-workbench",self.design_id,self.platform_name,self.platform_name,
                self.toolchain.name,evidence,GoalPreference.BALANCED,
                (QoRConstraint("l1_tool_runs",">=",1),),
                ("synth","floorplan","place","cts","route","finish"),
                ("core_utilization_pct","place_density","minimum_die_size_um"),
                AgentBudget(3,4,7200),allowed_tools)
        return TrustedGoalPolicy("workbench-policy","v1","platform",provenance,"workbench-project","workbench-design","workbench","workbench-pdk","workbench-toolchain",evidence,GoalPreference.BALANCED,(QoRConstraint("l1_tool_runs",">=",1),),("finish",),("place_density",),AgentBudget(3,4,30),allowed_tools)
    def _goal_provider(self):
        """Select the replaceable language front-end for this Session.

        ``tutorial`` uses the deterministic mux parser; ``codex`` uses the
        managed Codex CLI as a structured GoalDraft provider.  The provider
        only proposes typed language facts: GoalFinalizer and Policy keep all
        authority, and a failing model raises instead of silently falling back.
        """
        if self.model_provider == "codex":
            if self._codex_provider is None:
                self._codex_provider = CodexGoalDraftProvider()
            return self._codex_provider
        return (MuxHandsOnSemanticProvider(
            design=self.design_id,
            managed_design=(self.profile.design_label if self.profile else self.design_id),
            design_context=(self.profile.design_context if self.profile else
                            "managed_mux_default_corner_baseline"),
        ) if self.profile else _Provider())

    def start(self, text, *, teaching_mode="guided"):
        mode = validate_teaching_mode(teaching_mode).value
        provider = self._goal_provider()
        session = self.sessions.start(
            text, provider, self.policy(),
            required_questions=self.required_goal_questions,
        )
        self._teaching_modes[session.session_id] = mode
        if session.goal_id:
            goal = self._goal(session.trace_id, session.goal_id)
            self._save(session.session_id, DesignState(
                f"state-{uuid.uuid4().hex}", session.goal_id, 0, "running", None,
                {}, goal.budget, evidence=(goal.rtl_artifact,)), None)
        return session
    def answer(self,sid,answers):
        rows=tuple(ClarificationAnswer(a["question_id"],ClarificationField(a["field"]),a["value"]) for a in answers)
        provider = self._goal_provider()
        session=self.sessions.answer(sid,provider,rows)
        if session.goal_id:
            goal=self._goal(session.trace_id,session.goal_id)
            self._save(sid,DesignState(f"state-{uuid.uuid4().hex}",session.goal_id,0,"running",None,{},goal.budget,evidence=(goal.rtl_artifact,)),None)
        return session
    def _bridge(self, goal, *, wait=True, target_stage="finish", teaching_mode=None):
        """Build an immutable base TaskSpec; Runtime remains the run authority."""
        if self.backend == "orfs":
            if target_stage not in goal.allowed_stages: raise ValueError("stage is outside the finalized Goal")
            options = {"platform_name":self.platform_name,"target_stage":target_stage,
                       "clock_period_ns":self.clock_period_ns,
                       "core_utilization_pct":10.0,"place_density":0.45,
                       "stage_timeout_seconds":3600,"timeout_seconds":7200}
            labels = {"surface":"l1-workbench","mode":"baseline",
                      "teaching_mode": teaching_mode or "guided"}
            if self.reference_design is not None:
                baseline = dict(self.reference_design.native_baseline_overrides)
                options.update({
                    "clock": self.reference_design.clock,
                    "core_utilization_pct": baseline.pop("core_utilization_pct"),
                    "place_density": baseline.pop("place_density"),
                    "flow_parameters": baseline,
                    "rtl_files": self.reference_design.rtl_files,
                    "rtl_root": self.reference_design.rtl_root,
                    "rtl_include_dirs": self.reference_design.include_dirs,
                    "synth_hdl_frontend": self.reference_design.synth_hdl_frontend,
                    "design_options": dict(self.reference_design.design_options),
                    "sdc_path": self.reference_design.sdc_path,
                    "fast_route_tcl_path": self.reference_design.fast_route_tcl_path,
                })
                labels.update({
                    "reference_design": self.reference_design.design,
                    "design_bundle_sha256": self.reference_design.source_fingerprint,
                    "orfs_commit": self.reference_design.orfs_commit,
                })
            task=self.factory.build(RTLToGDSRequest(rtl_path=str(self.rtl),project_id=goal.project_id,design_id=goal.design_id,top=self.top,task_id=f"l1-orfs-{uuid.uuid4().hex}",labels=labels,options=options))
            factory=self.factory
        else:
            task=TaskSpec(f"l1-workbench-{uuid.uuid4().hex}",goal.project_id,goal.design_id,plugin_id="l1-runtime-smoke",inputs={"kind":"bounded_l1_tool","bounded_mode":"normal" if wait else "cancellable"},expected_artifacts=("report",),timeout_seconds=30)
            class Factory:
                capability="eda.rtl_to_gds"
                def validate_task(self,t): t.validate()
                def reconfigure(self,t,v): return replace(t,parameters={**t.parameters,**dict(v)})
            factory=Factory()
        return L1RuntimeBridge(
            self.runtime, task, factory,
            cancel_port=self.runtime.store.request_cancel,
            knowledge_factory=self.knowledge_factory,
        )
    def execute(self,sid,summary,*,wait=True):
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); state, _=self._load(sid)
        bridge=self._bridge(goal,wait=wait, teaching_mode=self._teaching_modes.get(sid))
        loop=L1DurableLoop(self.loop_store,bridge,self.trace); call=SemanticToolCall(f"call-{uuid.uuid4().hex}",goal.goal_id,state.state_id,ToolName.RUN_FULL_FLOW,{},"l1-workbench")
        trusted=self.policy(); identity=TrustedPolicyIdentity(trusted.policy_id,trusted.policy_version,trusted.issuer,trusted.provenance)
        plan=loop.plan_validate_execute(session.trace_id,goal,state,call,identity,planner_summary=summary)
        self._save(sid,state,plan["plan_id"])
        def finish():
            self.runtime.execute_once(plan["run_id"])
            successor=loop.observe(session.trace_id,state,plan["plan_id"],next_state_id=f"state-{uuid.uuid4().hex}")
            self._save(sid,successor,plan["plan_id"])
        if wait: finish(); return plan, self._load(sid)[0]
        threading.Thread(target=finish,daemon=True).start(); return plan, state
    def set_flow_params(self,sid,values,summary):
        """Persist one Policy-approved parameter proposal; it does not run EDA."""
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); state,_=self._load(sid)
        bridge=self._bridge(goal, teaching_mode=self._teaching_modes.get(sid)); loop=L1DurableLoop(self.loop_store,bridge,self.trace)
        call=SemanticToolCall(f"call-{uuid.uuid4().hex}",goal.goal_id,state.state_id,ToolName.SET_FLOW_PARAMS,{"values":dict(values)},"l1-workbench")
        trusted=self.policy(); identity=TrustedPolicyIdentity(trusted.policy_id,trusted.policy_version,trusted.issuer,trusted.provenance)
        plan=loop.plan_validate_execute(session.trace_id,goal,state,call,identity,planner_summary=summary)
        proposal_id=f"proposal-{call.call_id}"
        # SET_FLOW_PARAMS is a durable proposal, not a Runtime submission; its
        # stable identity is derived by L1DurableLoop and consumed exactly once
        # by a later RUN_FULL_FLOW/RUN_STAGE plan.
        return {**plan,"proposal_id":proposal_id}
    def run_candidate(self,sid,proposal_id,summary,*,wait=True):
        """Consume exactly one durable ParameterPlan in a Runtime candidate run."""
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); state,_=self._load(sid)
        bridge=self._bridge(goal, teaching_mode=self._teaching_modes.get(sid)); loop=L1DurableLoop(self.loop_store,bridge,self.trace)
        call=SemanticToolCall(f"call-{uuid.uuid4().hex}",goal.goal_id,state.state_id,ToolName.RUN_FULL_FLOW,{"proposal_id":proposal_id},"l1-workbench")
        trusted=self.policy(); identity=TrustedPolicyIdentity(trusted.policy_id,trusted.policy_version,trusted.issuer,trusted.provenance)
        plan=loop.plan_validate_execute(session.trace_id,goal,state,call,identity,planner_summary=summary)
        self._save(sid,state,plan["plan_id"])
        def finish():
            self.runtime.execute_once(plan["run_id"])
            successor=loop.observe(session.trace_id,state,plan["plan_id"],next_state_id=f"state-{uuid.uuid4().hex}")
            self._save(sid,successor,plan["plan_id"])
        if wait: finish(); return plan,self._load(sid)[0]
        threading.Thread(target=finish,daemon=True).start(); return plan,state
    def propose_m1_candidate(self,sid):
        """Create a visible, evidence-backed M1 proposal; it does not run EDA."""
        if self.backend != "orfs":
            raise ValueError("M1 QoR proposals require the artifact-backed ORFS backend")
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); baseline,_=self._load(sid)
        proposal=M1EvidencePlanner.propose(goal,baseline)
        plan=self.set_flow_params(sid,proposal.values,proposal.summary)
        return {"proposal": {"values":proposal.values,"summary":proposal.summary,"hypothesis":proposal.hypothesis}, **plan}
    def compare_m1_candidate(self,sid,baseline_run_id,summary=None):
        """Compare baseline and current candidate through the typed Runtime read surface."""
        if self.backend != "orfs":
            raise ValueError("M1 QoR comparison requires the artifact-backed ORFS backend")
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); candidate,_=self._load(sid)
        candidate_run_id=candidate.diagnosis.get("runtime_run_id")
        if not isinstance(baseline_run_id,str) or not baseline_run_id or not isinstance(candidate_run_id,str) or not candidate_run_id:
            raise ValueError("M1 comparison requires baseline and observed candidate Runtime run ids")
        baseline_state=self._state_for_run(session.trace_id,baseline_run_id)
        bridge=self._bridge(goal); loop=L1DurableLoop(self.loop_store,bridge,self.trace)
        call=SemanticToolCall(f"call-{uuid.uuid4().hex}",goal.goal_id,candidate.state_id,ToolName.COMPARE_RUNS,{"left_run_id":baseline_run_id,"right_run_id":candidate_run_id,"metrics":["setup_wns_ns","area_um2","drc_errors"]},"m1-evidence-planner")
        trusted=self.policy(); identity=TrustedPolicyIdentity(trusted.policy_id,trusted.policy_version,trusted.issuer,trusted.provenance)
        plan=loop.plan_validate_execute(session.trace_id,goal,candidate,call,identity,planner_summary=summary or "Compare canonical baseline and candidate Runtime QoR facts.")
        decision,decision_summary,hypothesis=M1EvidencePlanner.decide(baseline_state,candidate)
        basis=tuple(event.event_id for event in self.trace.store.read(session.trace_id)[-3:])
        event=self.trace.record_reflection(session.trace_id,candidate,summary=decision_summary,decision=decision,evidence=candidate.evidence,hypotheses=hypothesis,basis_event_ids=basis)
        baseline_area=baseline_state.metrics.get("area_um2")
        candidate_area=candidate.metrics.get("area_um2")
        ratio=(candidate_area / baseline_area
               if isinstance(baseline_area,(int,float)) and not isinstance(baseline_area,bool)
               and isinstance(candidate_area,(int,float)) and not isinstance(candidate_area,bool)
               and baseline_area > 0 else None)
        return {"comparison":plan,"baseline_run_id":baseline_run_id,"candidate_run_id":candidate_run_id,
                "area_baseline_ratio":ratio,"decision":decision,"decision_reason":hypothesis["reason"],
                "decision_summary":decision_summary,"reflection_event_id":event.event_id}
    def query(self,sid,kind,summary,*,limit=20):
        """Read only the current Goal-owned Runtime result through typed tools."""
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); state, _=self._load(sid)
        run_id=state.diagnosis.get("runtime_run_id")
        if not isinstance(run_id,str) or not run_id: raise ValueError("query requires an observed Runtime run for this Session")
        tools={"timing":ToolName.QUERY_TIMING,"congestion":ToolName.QUERY_CONGESTION,
               "drc":ToolName.QUERY_DRC,"power":ToolName.QUERY_POWER,
               "metrics":ToolName.QUERY_STAGE_METRICS}
        try: tool=tools[kind]
        except KeyError as exc: raise ValueError("unknown L1 query kind") from exc
        if not isinstance(limit,int) or isinstance(limit,bool) or not 1 <= limit <= 256: raise ValueError("query limit is invalid")
        bridge=self._bridge(goal); loop=L1DurableLoop(self.loop_store,bridge,self.trace)
        call=SemanticToolCall(f"call-{uuid.uuid4().hex}",goal.goal_id,state.state_id,tool,{"run_id":run_id,"limit":limit},"l1-workbench")
        trusted=self.policy(); identity=TrustedPolicyIdentity(trusted.policy_id,trusted.policy_version,trusted.issuer,trusted.provenance)
        return loop.plan_validate_execute(session.trace_id,goal,state,call,identity,planner_summary=summary)
    def query_openroad_knowledge(self, sid, query, summary, *,
                                 purpose="knowledge", top_k=5):
        """Retrieve cited OpenROAD knowledge through Policy and Runtime."""
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); state,_=self._load(sid)
        bridge=self._bridge(goal); loop=L1DurableLoop(self.loop_store,bridge,self.trace)
        call=SemanticToolCall(
            f"call-{uuid.uuid4().hex}", goal.goal_id, state.state_id,
            ToolName.QUERY_OPENROAD_KNOWLEDGE,
            {"query":query,"purpose":purpose,"top_k":top_k}, "l1-workbench")
        trusted=self.policy(); identity=TrustedPolicyIdentity(trusted.policy_id,trusted.policy_version,trusted.issuer,trusted.provenance)
        return loop.plan_validate_execute(
            session.trace_id,goal,state,call,identity,planner_summary=summary)
    def artifact_excerpt(self,sid,kind,summary,*,max_bytes=4096):
        """Read one registered artifact by approved kind, never by path."""
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); state, _=self._load(sid)
        run_id=state.diagnosis.get("runtime_run_id")
        if not isinstance(run_id,str) or not run_id: raise ValueError("artifact query requires an observed Runtime run")
        if not isinstance(kind,str) or kind not in {"report","log","run_result","config"}: raise ValueError("artifact kind is not exposed by the L1 tutorial")
        if not isinstance(max_bytes,int) or isinstance(max_bytes,bool) or not 1 <= max_bytes <= 64 * 1024: raise ValueError("artifact excerpt size is invalid")
        view=self.runtime.describe(run_id)
        matches=[item for stage in view.get("stages",()) for attempt in stage.get("attempts",()) for item in attempt.get("artifacts",()) if item.get("kind")==kind]
        if not matches: raise ValueError("current Runtime run has no registered requested artifact kind")
        artifact_id=matches[0].get("artifact_id")
        if not isinstance(artifact_id,str) or not artifact_id: raise ValueError("registered artifact is missing its identity")
        bridge=self._bridge(goal); loop=L1DurableLoop(self.loop_store,bridge,self.trace)
        call=SemanticToolCall(f"call-{uuid.uuid4().hex}",goal.goal_id,state.state_id,ToolName.QUERY_ARTIFACT_EXCERPT,{"run_id":run_id,"artifact_id":artifact_id,"offset":0,"max_bytes":max_bytes},"l1-workbench")
        trusted=self.policy(); identity=TrustedPolicyIdentity(trusted.policy_id,trusted.policy_version,trusted.issuer,trusted.provenance)
        return loop.plan_validate_execute(session.trace_id,goal,state,call,identity,planner_summary=summary)
    def run_stage(self,sid,stage,summary,*,wait=True):
        """Submit one allowed ORFS stage under the same Runtime lifecycle."""
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); state, _=self._load(sid)
        bridge=self._bridge(goal,wait=wait,target_stage=stage); loop=L1DurableLoop(self.loop_store,bridge,self.trace)
        call=SemanticToolCall(f"call-{uuid.uuid4().hex}",goal.goal_id,state.state_id,ToolName.RUN_STAGE,{"stage":stage},"l1-workbench")
        trusted=self.policy(); identity=TrustedPolicyIdentity(trusted.policy_id,trusted.policy_version,trusted.issuer,trusted.provenance)
        plan=loop.plan_validate_execute(session.trace_id,goal,state,call,identity,planner_summary=summary)
        self._save(sid,state,plan["plan_id"])
        def finish():
            self.runtime.execute_once(plan["run_id"])
            successor=loop.observe(session.trace_id,state,plan["plan_id"],next_state_id=f"state-{uuid.uuid4().hex}")
            self._save(sid,successor,plan["plan_id"])
        if wait: finish(); return plan,self._load(sid)[0]
        threading.Thread(target=finish,daemon=True).start(); return plan,state
    def advance(self,sid):
        """Execute one evidence-backed tutorial decision; never accept a shell action."""
        if self.model_provider == "codex":
            return self.model_advance(sid)
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); state,_=self._load(sid)
        decision=TutorialEvidencePlanner.choose(goal,state,self.events(sid))
        payload={"decision":{"action":decision.action,"summary":decision.summary,"hypothesis":decision.hypothesis,"basis_event_ids":list(decision.basis_event_ids)}}
        if decision.action == "run_full_flow":
            plan,next_state=self.execute(sid,decision.summary); payload.update({"plan":plan,"state":next_state.to_dict()})
        elif decision.action == "query_timing":
            payload["plan"]=self.query(sid,"timing",decision.summary)
        elif decision.action == "reflect_continue":
            event=self.trace.record_reflection(session.trace_id,state,summary=decision.summary,decision="continue",evidence=state.evidence,hypotheses=decision.hypothesis,basis_event_ids=decision.basis_event_ids)
            payload["reflection_event_id"]=event.event_id
        elif decision.action == "run_route":
            plan,next_state=self.run_stage(sid,"route",decision.summary); payload.update({"plan":plan,"state":next_state.to_dict()})
        elif decision.action == "query_drc":
            payload["plan"]=self.query(sid,"drc",decision.summary)
        elif decision.action == "stop":
            event=self.trace.record_reflection(session.trace_id,state,summary=decision.summary,decision="stop",evidence=state.evidence,hypotheses=decision.hypothesis,basis_event_ids=decision.basis_event_ids)
            payload["reflection_event_id"]=event.event_id
        else: raise RuntimeError("tutorial planner returned an unsupported action")
        return payload
    def model_advance(self, sid, *, wait=True):
        """Ask managed Codex for one typed call, then pass it through Policy/Runtime."""
        session = self.sessions.store.get(sid)
        goal = self._goal(session.trace_id, session.goal_id)
        state, _ = self._load(sid)
        events = self.trace.store.read(session.trace_id)
        model_calls = [event for event in events
                       if event.kind.value == "tool_called"
                       and event.facts.get("producer") == "codex-cli-l1-goal-v1"]
        if len(model_calls) >= goal.budget.max_llm_calls:
            raise ValueError("DesignGoal LLM-call budget is exhausted")
        hits = self._model_knowledge_hits(state, events)
        provider = self._goal_provider()
        call_id = f"call-{uuid.uuid4().hex}"
        proposal = L1ModelBoundary.propose_tool(
            provider, goal, state, hits, call_id=call_id)
        bridge = self._bridge(goal, wait=wait)
        loop = L1DurableLoop(self.loop_store, bridge, self.trace)
        trusted = self.policy()
        identity = TrustedPolicyIdentity(
            trusted.policy_id, trusted.policy_version, trusted.issuer,
            trusted.provenance)
        plan = loop.plan_validate_execute(
            session.trace_id, goal, state, proposal.call, identity,
            planner_summary=proposal.decision_summary)
        result = {"model_proposal": {
            "call": proposal.call.to_dict(),
            "decision_summary": proposal.decision_summary,
            "citations": [item.to_dict() for item in proposal.citations],
        }, "plan": plan}
        run_id = plan.get("run_id")
        if isinstance(run_id, str) and proposal.call.tool in {
                ToolName.RUN_STAGE, ToolName.RUN_FULL_FLOW}:
            self._save(sid, state, plan["plan_id"])
            if wait:
                self.runtime.execute_once(run_id)
                successor = loop.observe(
                    session.trace_id, state, plan["plan_id"],
                    next_state_id=f"state-{uuid.uuid4().hex}")
                self._save(sid, successor, plan["plan_id"])
                result["state"] = successor.to_dict()
        return result
    @staticmethod
    def _model_knowledge_hits(state, events):
        """Build bounded evidence indexes; raw artifacts remain in Runtime."""
        pointers = list(state.evidence)
        if not pointers:
            raise ValueError("model tool planning requires evidence-backed state")
        state_excerpt = {
            "kind": "current_design_state", "status": state.status,
            "completed_stage": state.completed_stage, "metrics": state.metrics,
            "remaining_budget": state.remaining_budget.to_dict(),
            "runtime_run_id": state.diagnosis.get("runtime_run_id"),
        }
        hits = [L1KnowledgeHit(
            json.dumps(state_excerpt, sort_keys=True), pointers[0])]
        for event in events[-8:]:
            if event.kind.value not in {"tool_called", "tool_receipt", "state_transition", "reflection_recorded"}:
                continue
            # A trace event is durable state, but it is not automatically an
            # EvidencePointer.  In particular, proposal-only tool calls can
            # legitimately have no artifact evidence.  Do not invent a new
            # reference scheme for them: only expose events that already carry
            # a contract-valid evidence pointer to the untrusted model.
            if not event.evidence:
                continue
            payload = {"kind": event.kind.value, "event_id": event.event_id,
                       "planner_summary": event.planner_summary,
                       "facts": event.facts}
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
            hits.append(L1KnowledgeHit(raw[:4000], event.evidence[0]))
        return tuple(hits[:8])
    def l2_upgrade(self, sid, *, wait=False):
        """Retired direct-submission path (ba88043); use :l2 to pass the gate."""
        raise ValueError("direct L2 submission is retired; use the :l2 escalation gate, then the durable external campaign controller")
    def l2_escalate(self, sid, *, summary=None):
        """Visible L1→L2 escalation gate (authorization stage only).

        Records a durable ``escalate`` reflection and, when the trace holds
        two distinct measured Runtime observations plus this newest escalation,
        issues the typed ``L2HandoffAuthorization`` and freezes an
        ``OptimizationRequest``.  It never submits ORFS-Agent work itself:
        execution belongs to the durable external campaign controller, exactly
        like the product L2 path.  No optimizer, shell, or QoR claim is made.
        """
        if self.backend != "orfs" or not self.orfs_agent_source:
            raise ValueError("L2 escalation requires real ORFS and admitted A2-ORFO/ORFS-Agent")
        session = self.sessions.store.get(sid)
        goal = self._goal(session.trace_id, session.goal_id)
        state, _ = self._load(sid)
        if state.status != "observed" or not state.evidence:
            raise ValueError("L2 escalation requires an evidence-backed observed L1 state")
        transitions = [event for event in self.trace.store.read(session.trace_id)
                       if event.kind.value == "state_transition"
                       and event.facts.get("terminal_status") == "succeeded"
                       and event.facts.get("run_id")]
        if len({event.facts.get("run_id") for event in transitions}) < 2:
            raise ValueError("L2 escalation requires distinct measured baseline and candidate Runtime observations")
        basis = tuple(event.event_id for event in transitions[-3:])
        existing = [event for event in self.trace.store.read(session.trace_id)
                    if event.kind.value == "l2_handoff_authorized"
                    and event.facts.get("source_state_id") == state.state_id]
        if len(existing) > 1:
            raise ValueError("current L1 state has ambiguous durable L2 authorizations")
        if existing:
            event = existing[0]
            authorization = L2HandoffAuthorization(
                str(event.facts["handoff_id"]), str(event.facts["l1_trace_id"]),
                str(event.facts["goal_id"]), str(event.facts["source_state_id"]),
                str(event.facts["reflection_event_id"]), str(event.facts["baseline_run_id"]),
                str(event.facts["candidate_run_id"]), tuple(event.evidence),
            )
            reflection_id = authorization.reflection_event_id
        else:
            reflection = self.trace.record_reflection(
                session.trace_id, state, summary=summary or "Operator requests entering the admitted L2 search stage.",
                decision="escalate", evidence=state.evidence, hypotheses={}, basis_event_ids=basis)
            authorization = L1L2AuthorizationService(self.trace).authorize(session.trace_id, goal, state)
            reflection_id = reflection.event_id
        lock = Path(__file__).resolve().parents[2] / "integrations/a2_orfo/source.lock.json"
        domain = self.a2_orfo_source / "AutoTuner-integration/ORFS-with-AutoTuner/constraints.json"
        required_eda_runs = (
            self.l2_protocol_budget["initial_samples"]
            + self.l2_protocol_budget["feedback_steps"] *
              self.l2_protocol_budget["suggestions_per_step"]
            + self.l2_protocol_budget["confirmations"]
        )
        request = OptimizationRequest(
            f"l2-request-{authorization.authorization_id.removeprefix('l2-auth-')}", session.trace_id, goal.goal_id, state.state_id,
            "a2-orfo", "optimizer.l2.a2-orfo-feedback",
            "run complete A2-ORFO optimization over the full 12-D variable-clock ORFS domain",
            EvidencePointer("artifact:a2-orfo-source-lock", hashlib.sha256(lock.read_bytes()).hexdigest()),
            EvidencePointer("artifact:a2-orfo-full-constraints", hashlib.sha256(domain.read_bytes()).hexdigest()),
            "a2-upstream-six-iteration-seed-policy-v1",
            AgentBudget(required_eda_runs,
                        max(goal.budget.max_llm_calls,
                            self.l2_protocol_budget["feedback_steps"] + 1),
                        min(7 * 86_400, max(goal.budget.max_wall_clock_seconds,
                                          required_eda_runs * 10_800)),
                        self.l2_max_parallel))
        manifest = self.runtime.registry.resolve(
            "a2-orfo", capability=request.capability, arch=platform.machine())
        initial_state = {
            "status": "authorized", "protocol_mode": "a2_orfo_upstream_full_12d_v1",
            "request": request.to_dict(), "authorization": authorization.to_dict(),
            "goal": goal.to_dict(), "source_state": state.to_dict(),
            "optimizer_plugin": f"{manifest.plugin_id}@{manifest.plugin_version}",
            "required_eda_runs": required_eda_runs,
            "claim_boundary": "controller authorized; no optimizer or candidate task submitted",
        }
        checkpoint = OptimizationHandoffService(
            DEFAULT_PRODUCT_SURFACE, None, trace_store=self.trace.store,
            consumption_store=self.l2_handoff_store,
        ).create_authorized_controller(
            self.l2_checkpoints, request, goal, state, authorization, manifest,
            pipeline_kind=A2_ORFO_CAMPAIGN_KIND, initial_state=initial_state,
        )
        return {"reflection_event_id": reflection_id,
                "authorization": authorization.to_dict(),
                "request": request.to_dict(),
                "pipeline_id": checkpoint["pipeline_id"],
                "pipeline_status": checkpoint["state"]["status"],
                "claim_boundary": "durable A2-ORFO controller authorized; no policy or EDA task was submitted"}
    def l2_configure(self, sid, pipeline_id, *, objective="ECP",
                     initialization_seed=401, screening_seed=401,
                     confirmation_seeds=None):
        """Freeze the complete upstream domain and make an authorized L2 ready."""
        if not all((self.orfs_agent_source, self.orfs_agent_paper_orfs,
                    self.orfs_agent_openroad_bin, self.orfs_agent_yosys_bin)):
            raise ValueError(
                "full L2 is not ready: admitted paper ORFS, OpenROAD, and Yosys are required")
        session = self.sessions.store.get(sid)
        goal = self._goal(session.trace_id, session.goal_id)
        checkpoint = self.l2_checkpoints.get(pipeline_id)
        bound_goal = checkpoint["state"].get("goal") or {}
        if (checkpoint["pipeline_kind"] != A2_ORFO_CAMPAIGN_KIND
                or bound_goal.get("goal_id") != goal.goal_id
                or goal.design_id != self.design_id):
            raise ValueError("L2 pipeline is not bound to this Session and design")
        receipts = orfs_agent_full_protocol_receipts(
            source_root=self.orfs_agent_source,
            paper_orfs_root=self.orfs_agent_paper_orfs,
            openroad_bin=self.orfs_agent_openroad_bin,
            yosys_bin=self.orfs_agent_yosys_bin,
            design=self.design_id, platform_name=self.platform_name,
            paper_runtime_environment=self.orfs_agent_paper_environment,
        )
        a2_protocol = {
            "protocol_id": "a2-orfo-product-full-v1",
            "a2_orfo_commit": "8b20a3c1f22934a39c7ba51ed0ec6dffe730da2d",
            "orfs_executor_commit": "730f1fa11f9c17c0aaac332412af2b2538f42e9b",
            "design": self.design_id, "platform": self.platform_name,
            "objective_set": ["ECP", "DWL", "COMBO"],
            "seed_policy": "a2-upstream-six-iteration-seed-policy-v1",
            "budget": {"minimum_successful_observations": 4,
                       "feedback_steps": self.l2_protocol_budget["feedback_steps"]},
            "evaluator": "protected-orfs-agent-full-v1",
            "objective_baselines": {"ecp": 4.721, "dwl": 589825.0},
            "design_bundle_sha256": receipts["design_bundle_sha256"],
            "pdk_bundle_sha256": receipts["pdk_bundle_sha256"],
            "toolchain_receipt_sha256": receipts["toolchain_receipt_sha256"],
        }
        execution_protocol = {
            "protocol_id": "a2-orfo-product-orfs-execution-v1",
            "orfs_agent_commit": "730f1fa11f9c17c0aaac332412af2b2538f42e9b",
            "orfs_commit": "ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54",
            "design": self.design_id, "platform": self.platform_name,
            "objective_set": ["ECP", "DWL", "COMBO"],
            "seed_policy": "a2-upstream-six-iteration-seed-policy-v1",
            "budget": {
                "initial_samples": self.l2_protocol_budget["initial_samples"],
                "rounds": self.l2_protocol_budget["feedback_steps"],
                "suggestions_per_round": self.l2_protocol_budget["suggestions_per_step"],
                "confirmations": self.l2_protocol_budget["confirmations"],
            },
            "evaluator": "protected-orfs-agent-full-v1",
            "initialization_method": "upstream:A2-ORFO.OptimizationWorkflow.generate_initial_parameters",
            "design_bundle_sha256": receipts["design_bundle_sha256"],
            "pdk_bundle_sha256": receipts["pdk_bundle_sha256"],
            "toolchain_receipt_sha256": receipts["toolchain_receipt_sha256"],
        }
        a2_domain = A2ORFODomain.from_upstream(
            source_root=self.a2_orfo_source, design=self.design_id,
            platform_name=self.platform_name, experiment_protocol=a2_protocol)
        execution_domain = ORFSAgentFullDomain.from_upstream(
            source_root=self.orfs_agent_source, design=self.design_id,
            platform=self.platform_name, experiment_protocol=execution_protocol,
        )
        seeds = (list(confirmation_seeds) if confirmation_seeds is not None
                 else [503 + 98 * index
                       for index in range(self.l2_protocol_budget["confirmations"])])
        optimizer_seeds = tuple(
            int(initialization_seed) + 2 * index
            for index in range(self.l2_protocol_budget["feedback_steps"] + 1))
        return self.l2_campaign.configure(
            pipeline_id, a2_domain=a2_domain,
            execution_domain=execution_domain, objective=objective,
            initial_observations=(), optimizer_seeds=optimizer_seeds,
            or_seed=int(screening_seed),
            n_suggestions=self.l2_protocol_budget["suggestions_per_step"],
            confirmation_seeds=seeds,
            bootstrap_samples=self.l2_protocol_budget["initial_samples"])
    def l2_advance(self, sid, pipeline_id, *, execute=False, max_parallel=1):
        """Advance one durable full-campaign transition through Runtime."""
        session = self.sessions.store.get(sid)
        goal = self._goal(session.trace_id, session.goal_id)
        checkpoint = self.l2_checkpoints.get(pipeline_id)
        if (checkpoint["state"].get("goal") or {}).get("goal_id") != goal.goal_id:
            raise ValueError("L2 pipeline is not bound to this Session")
        return self.l2_campaign.advance(
            pipeline_id, execute=bool(execute), max_parallel=int(max_parallel))
    def l2_status(self, sid, pipeline_id):
        """Return one Session-bound durable L2 checkpoint without executing work."""
        session = self.sessions.store.get(sid)
        goal = self._goal(session.trace_id, session.goal_id)
        checkpoint = self.l2_checkpoints.get(pipeline_id)
        if (checkpoint["pipeline_kind"] != A2_ORFO_CAMPAIGN_KIND
                or (checkpoint["state"].get("goal") or {}).get("goal_id") != goal.goal_id):
            raise ValueError("L2 pipeline is not bound to this Session")
        return checkpoint
    def l2_list(self, sid):
        """List only full-campaign checkpoints bound to this Session's Goal."""
        session = self.sessions.store.get(sid)
        goal = self._goal(session.trace_id, session.goal_id)
        return [checkpoint for checkpoint in self.l2_checkpoints.list(
            pipeline_kind=A2_ORFO_CAMPAIGN_KIND, limit=1000)
            if (checkpoint["state"].get("goal") or {}).get("goal_id") == goal.goal_id]
    def _l2_candidates_for_run(self, run_id):
        return self.l2_evidence.candidates_for_run(run_id)
    def _l2_observation_for_run(self, run_id, _state):
        return self.l2_evidence.observation_for_run(run_id, _state)
    def _l2_registered_json(self, run_id, kind, *, artifact_id=None):
        return self.l2_evidence.registered_json(
            run_id, kind, artifact_id=artifact_id)
    def cancel(self,sid,reason):
        state,plan=self._load(sid); self.runtime.store.request_cancel(self.loop_store.get(plan)["run_id"]); return {"status":"cancel_requested","reason":reason}
    def recover(self,sid):
        session=self.sessions.recover(sid); state,plan_id=self._load(sid)
        if not plan_id: return session
        plan=self.loop_store.get(plan_id)
        goal=self._goal(session.trace_id,session.goal_id); bridge=self._bridge(goal)
        loop=L1DurableLoop(self.loop_store,bridge,self.trace)
        if plan["status"] == "prepared":
            plan=loop.recover_submission(session.trace_id,plan_id)
        if plan["status"] == "submitted" and plan["run_id"]:
            terminal=self.runtime.describe(plan["run_id"])["run"].get("status")
            already_observed=state.diagnosis.get("runtime_run_id") == plan["run_id"]
            if terminal in {"succeeded","failed","cancelled","timed_out","lost"} and not already_observed:
                successor=loop.observe(session.trace_id,state,plan_id,next_state_id=f"state-{uuid.uuid4().hex}")
                self._save(sid,successor,plan_id)
        return session
    def events(self,sid,after=-1): return [e.to_dict() for e in self.sessions.events(sid,after_sequence=after)]
    def teaching(self,sid):
        """Read-only per-event teaching replay derived only from stored facts."""
        return teaching_replay(self.events(sid))
    def _goal(self,trace_id,gid):
        from openroad_platform_contracts.agent_control import DesignGoal
        return DesignGoal.from_dict(next(e.facts["goal_ir"] for e in self.trace.store.read(trace_id) if e.goal_id==gid and e.kind.value=="goal_finalized"))
    def _save(self,sid,state,plan):
        with sqlite3.connect(self.root/"workbench.sqlite") as c:c.execute("INSERT OR REPLACE INTO session_state VALUES(?,?,?)",(sid,json.dumps(state.to_dict()),plan))
    def _load(self,sid):
        with sqlite3.connect(self.root/"workbench.sqlite") as c:r=c.execute("SELECT state_json,plan_id FROM session_state WHERE session_id=?",(sid,)).fetchone()
        if not r: raise ValueError("session has no finalized Goal state")
        return DesignState.from_dict(json.loads(r[0])),r[1]
    def _state_for_run(self,trace_id,run_id):
        for event in reversed(self.trace.store.read(trace_id)):
            if event.kind.value == "state_transition" and event.facts.get("run_id") == run_id:
                return DesignState.from_dict(event.facts["state_after"])
        raise ValueError("Runtime run has no observed DesignState in this Session")
