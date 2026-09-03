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

    @staticmethod
    def _initial(text: str) -> dict:
        folded = text.lower()
        is_optimize = any(word in folded for word in ("improve", "optimize", "改善", "优化"))
        interpretation = {
            "intent": "optimize" if is_optimize else "execute",
            "design": "mux_2to1" if "mux" in folded else "managed_tutorial_mux",
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
        prompts = {
            "objective": (ClarificationField.OBJECTIVE, "Choose objective: timing, balanced, area, or power."),
            "constraints": (ClarificationField.CONSTRAINTS, "Confirm constraints exactly: drc_zero_area_plus_3pct."),
            "clock_sdc": (ClarificationField.CLOCK_SDC_POLICY, "Confirm protected inputs exactly: protect_clock_sdc."),
            "change_scope": (ClarificationField.CHANGE_SCOPE, "Choose allowed scope: registered_parameters_only."),
            "budget": (ClarificationField.BUDGET, "Choose maximum EDA runs: 1, 2, or 3."),
            "design_context": (ClarificationField.DESIGN_CONTEXT, "Confirm the managed baseline and timing corner: managed_mux_default_corner_baseline."),
        }
        questions = []
        for question_id in ("objective", "constraints", "clock_sdc", "change_scope", "budget"):
            field, prompt = prompts[question_id]
            questions.append(ClarificationQuestion(question_id, field, prompt, recognized.get(question_id) is None))
        # Baseline/corner and allowed parameter scope were absent from the
        # natural-language request; these are real blocking questions.
        questions.append(ClarificationQuestion("design_context", *prompts["design_context"], True))
        return {"interpretation": interpretation, "field_sources": sources,
                "questions": questions, "answers": recognized}

    def complete(self, request):
        if request["kind"] != "goal_draft":
            prior = request["prior_draft"]
            return {"schema_version": 1, "request_text": prior["request_text"],
                    "intent": prior["intent"], "questions": prior["questions"],
                    "answers": request["answers"], "interpretation": prior.get("interpretation", {}),
                    "field_sources": prior.get("field_sources", {})}
        parsed = self._initial(request["request_text"])
        answers = []
        for question in parsed["questions"]:
            value = parsed["answers"].get(question.question_id)
            if value:
                answers.append({"schema_version": 1, "question_id": question.question_id,
                                "field": question.field.value, "value": value})
        return {"schema_version": 1, "request_text": request["request_text"],
                "intent": parsed["interpretation"]["intent"],
                "questions": [item.to_dict() for item in parsed["questions"]], "answers": answers,
                "interpretation": parsed["interpretation"], "field_sources": parsed["field_sources"]}
