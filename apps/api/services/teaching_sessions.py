"""Owner-scoped HTTP operations over the existing L1 experiment service."""


class TeachingSessions:
    def __init__(self, workbench, auth):
        self.workbench, self.auth = workbench, auth

    def create(self, payload, owner_id):
        session = self.workbench.start(
            payload["text"], teaching_mode=payload.get("teaching_mode", "guided"),
            teaching_context=payload.get("teaching_context"))
        self.auth.bind_resource("teaching_session", session.session_id, owner_id)
        return self.workbench.snapshot(session.session_id)

    def authorize(self, sid, owner_id):
        if not self.auth.owns_resource("teaching_session", sid, owner_id):
            raise KeyError("unknown teaching session")

    def get(self, sid, owner_id):
        self.authorize(sid, owner_id)
        return self.workbench.snapshot(sid)

    def list(self, owner_id):
        return [self.workbench.snapshot(sid)
                for sid in self.auth.resources_owned("teaching_session", owner_id)]

    def learning(self, sid, owner_id):
        view = self.get(sid, owner_id)
        state = view.get("state") or {}
        evidence = state.get("evidence") or []
        runtime = view.get("runtime") or {}
        run = runtime.get("run") or {}
        observed = state.get("status") == "observed"
        succeeded = run.get("status") == "succeeded"
        return {
            "session_id": sid,
            "evidence_count": len(evidence),
            "evidence": [{"ref": item.get("ref"), "sha256": item.get("sha256")}
                         for item in evidence if isinstance(item, dict) and item.get("ref")],
            "promotion": {
                "status": "eligible_for_review" if observed and succeeded and evidence else "not_eligible",
                "requirements": {"observed_runtime": observed,
                                  "successful_runtime": succeeded,
                                  "evidence_pointer": bool(evidence)},
                "authority": "Runtime evidence and teaching Session snapshot",
            },
        }

    def act(self, sid, action, payload, owner_id):
        self.authorize(sid, owner_id)
        svc = self.workbench
        summary = str(payload.get("decision_summary") or "Student confirmed this experiment step.")
        if action == "answers":
            svc.answer(sid, payload["answers"])
        elif action == "execute":
            svc.execute(sid, summary, wait=False)
        elif action == "parameters":
            return svc.set_flow_params(sid, payload["values"], summary)
        elif action == "m1-proposal":
            return svc.propose_m1_candidate(sid)
        elif action == "candidates":
            svc.run_candidate(sid, payload["proposal_id"], summary, wait=False)
        elif action == "l2-escalate":
            svc.l2_escalate(sid, summary=summary)
        elif action == "l2-configure":
            svc.l2_configure(sid, payload["pipeline_id"],
                             objective=payload.get("objective", "ECP"))
        elif action == "l2-advance":
            svc.l2_advance(sid, payload["pipeline_id"], execute=False,
                           max_parallel=svc.l2_max_parallel)
        elif action == "cancel":
            svc.cancel(sid, summary)
        elif action == "recover":
            svc.recover(sid)
        else:
            raise KeyError("unknown teaching action")
        return svc.snapshot(sid)
