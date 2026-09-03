from apps.l1_workbench.tutorial_semantic import MuxHandsOnSemanticProvider
from openroad_platform_scheduler.l1_model_boundary import L1ModelBoundary


REQUEST = "帮我改善 mux 的 setup timing，但面积不能比 baseline 增加超过 3%，不许修改 RTL/SDC，最多跑 3 次。"


def test_mux_hands_on_parser_preserves_user_semantics_and_only_asks_unknowns():
    draft = L1ModelBoundary.compile_draft(MuxHandsOnSemanticProvider(), REQUEST, draft_id="draft_1")
    assert draft.intent.value == "optimize"
    assert draft.interpretation == {
        "intent": "optimize", "design": "mux_2to1", "metric": "setup_wns_ns",
        "area_constraint": "baseline_ratio_lte_1_03", "rtl_sdc_protection": "protected",
        "budget": "3", "drc_constraint": "drc_zero",
    }
    assert draft.field_sources["area_constraint"] == "user"
    assert draft.field_sources["drc_constraint"] == "operator_profile"
    assert {item.question_id for item in draft.questions if item.blocking} == {
        "change_scope", "design_context",
    }
    assert {item.question_id for item in draft.answers} == {
        "objective", "constraints", "clock_sdc", "budget",
    }
