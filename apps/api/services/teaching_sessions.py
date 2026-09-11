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
