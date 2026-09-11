"""Deterministic M1 semantic draft for the managed mux Hands-on case.

This is deliberately a narrow, inspectable parser.  It never emits a command,
path, task, or parameter value; it merely preserves what the user said and
asks for remaining policy-relevant facts.  A future LLM provider must produce
the same GoalDraft contract.
"""
from __future__ import annotations

import re

from openroad_platform_contracts.l1_goal_draft import (
    ClarificationField, ClarificationQuestion,
)


class MuxHandsOnSemanticProvider:
    provider_id = "mux-hands-on-deterministic-v1"

    def __init__(self, *, design: str = "mux_2to1",
                 managed_design: str = "managed_tutorial_mux",
                 design_context: str = "managed_mux_default_corner_baseline") -> None:
        self.design = design
        self.managed_design = managed_design
        self.design_context = design_context

    def _initial(self, text: str) -> dict:
        folded = text.lower()
        is_optimize = any(word in folded for word in ("improve", "optimize", "改善", "优化"))
        # The legacy managed exercise is routinely named simply "mux" by an
        # operator even though its bound design id is ``mux_2to1``.  Preserve
        # that explicit user reference as the real design id; do not replace
        # it with the profile's generic display label.
        mentions_design = self.design.lower() in folded or (
            self.design == "mux_2to1" and re.search(r"\bmux\b", folded) is not None
        )
        interpretation = {
            "intent": "optimize" if is_optimize else "execute",
            "design": self.design if mentions_design else self.managed_design,
            "metric": "setup_wns_ns" if any(word in folded for word in ("setup", "timing", "时序")) else "unknown",
            "area_constraint": "baseline_ratio_lte_1_03" if re.search(r"(?:3\s*%|百分之?三|\+?3%)", folded) else "unknown",
            "rtl_sdc_protection": "protected" if ("rtl" in folded and "sdc" in folded) else "unknown",
            "budget": "3" if re.search(r"(?:最多|at most|max(?:imum)?).*?3|3.*?(?:次|runs?)", folded) else "unknown",
            "drc_constraint": "drc_zero" if "drc" in folded else "drc_zero",
        }
        sources = {name: "user" for name, value in interpretation.items() if value != "drc_zero"}
        sources["drc_constraint"] = "operator_profile" if "drc" not in folded else "user"
        answers = []
        recognized = {
            "objective": "timing" if interpretation["metric"] == "setup_wns_ns" else None,
            "constraints": "drc_zero_area_plus_3pct" if interpretation["area_constraint"] != "unknown" else None,
            "clock_sdc": "protect_clock_sdc" if interpretation["rtl_sdc_protection"] == "protected" else None,
            "budget": interpretation["budget"] if interpretation["budget"] != "unknown" else None,
        }
        return {"interpretation": interpretation, "field_sources": sources,
                "answers": recognized}

    def complete(self, request):
        if request["kind"] != "goal_draft":
            prior = request["prior_draft"]
            return {"schema_version": 1, "request_text": prior["request_text"],
                    "intent": prior["intent"], "questions": prior["questions"],
                    "answers": request["answers"], "interpretation": prior.get("interpretation", {}),
                    "field_sources": prior.get("field_sources", {})}
        parsed = self._initial(request["request_text"])
        questions = tuple(ClarificationQuestion.from_dict(item)
                          for item in request.get("required_questions", ()))
        expected_fields = {
            "objective": ClarificationField.OBJECTIVE,
            "constraints": ClarificationField.CONSTRAINTS,
            "clock_sdc": ClarificationField.CLOCK_SDC_POLICY,
            "budget": ClarificationField.BUDGET,
        }
        answers = []
        for question in questions:
            value = parsed["answers"].get(question.question_id)
            if value and expected_fields.get(question.question_id) is question.field:
                answers.append({"schema_version": 1, "question_id": question.question_id,
                                "field": question.field.value, "value": value})
        return {"schema_version": 1, "request_text": request["request_text"],
                "intent": parsed["interpretation"]["intent"],
                "questions": [item.to_dict() for item in questions], "answers": answers,
                "interpretation": parsed["interpretation"], "field_sources": parsed["field_sources"]}
