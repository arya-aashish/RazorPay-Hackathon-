"""
Tests the safety-net logic in agent_pipeline.py: the deterministic visual
verdict overriding the LLM crew's decision, and every fail-safe-to-review
path (malformed JSON, crashed crew, unrecognized action). Crew.kickoff()
and analyze_evidence_images() are both monkeypatched - real Agent/Task
objects still get constructed (that's pure object construction, no network),
but nothing here ever calls out to Gemini.
"""

import json

import pytest

from app import agent_pipeline


def _fake_crew_class(kickoff_result):
    """Returns a class that can replace agent_pipeline.Crew for one test."""

    class _FakeCrew:
        def __init__(self, *args, **kwargs):
            pass

        def kickoff(self):
            if isinstance(kickoff_result, Exception):
                raise kickoff_result
            return kickoff_result

    return _FakeCrew


def _patch_crew(monkeypatch, kickoff_result):
    monkeypatch.setattr(agent_pipeline, "Crew", _fake_crew_class(kickoff_result))


def _patch_no_visual_analysis_call(monkeypatch):
    """Fails the test loudly if the pipeline tries to run vision analysis
    when it shouldn't (e.g. a reason code that doesn't need it and no
    customer image was given)."""

    def _should_not_be_called(*args, **kwargs):
        raise AssertionError("analyze_evidence_images should not have been called for this case")

    monkeypatch.setattr(agent_pipeline, "analyze_evidence_images", _should_not_be_called)


# --- process_dispute() ------------------------------------------------

def test_auto_submit_with_no_visual_evidence_needed(monkeypatch):
    _patch_no_visual_analysis_call(monkeypatch)
    _patch_crew(
        monkeypatch,
        json.dumps({"action": "auto_submit", "reasoning": "delivered and signed", "evidence_summary": "ok"}),
    )

    result = agent_pipeline.process_dispute(
        dispute_id="d1",
        reason_code="product_not_received",  # not in the visual-evidence-required list
        customer_id="cust_1",
        order_id="order_1",
        customer_image_url=None,
    )

    assert result["action"] == "auto_submit"
    assert result["requires_human_review"] is False
    assert "visual_evidence" not in result


def test_visual_reason_without_an_uploaded_image_does_not_call_gemini(monkeypatch):
    # A visual reason code alone is not evidence. In particular, the pipeline
    # must not substitute a demo/mock image and report a made-up AI score.
    _patch_no_visual_analysis_call(monkeypatch)
    _patch_crew(
        monkeypatch,
        json.dumps({"action": "flag_for_review", "reasoning": "no photo", "evidence_summary": "none"}),
    )

    result = agent_pipeline.process_refund_claim(
        dispute_id="c_no_image",
        reason_code="not_as_described",
        customer_id="user_1",
        order_id="order_1",
    )

    assert "visual_evidence" not in result


def test_visual_veto_overrides_llm_auto_submit(monkeypatch):
    # The LLM crew wants to auto_submit, but the deterministic visual
    # analysis says this needs a human - the visual verdict must win.
    monkeypatch.setattr(
        agent_pipeline,
        "analyze_evidence_images",
        lambda **kwargs: {
            "requires_human_review": True,
            "human_review_reason": "Low-confidence or flagged visual evidence - needs human review.",
            "claim_supported": "uncertain",
        },
    )
    _patch_crew(
        monkeypatch,
        json.dumps({"action": "auto_submit", "reasoning": "looks fine to me", "evidence_summary": "ok"}),
    )

    result = agent_pipeline.process_dispute(
        dispute_id="d2",
        reason_code="not_as_described",
        customer_id="cust_2",
        order_id="order_2",
        customer_image_url="https://example.com/photo.jpg",
    )

    assert result["action"] == "flag_for_review"
    assert result["requires_human_review"] is True
    assert "visual evidence" in result["human_review_reason"].lower()
    assert result["visual_evidence"]["claim_supported"] == "uncertain"


def test_malformed_llm_json_fails_safe_to_review(monkeypatch):
    _patch_no_visual_analysis_call(monkeypatch)
    _patch_crew(monkeypatch, "this is not json at all")

    result = agent_pipeline.process_dispute(
        dispute_id="d3",
        reason_code="product_not_received",
        customer_id="cust_3",
        order_id="order_3",
    )

    assert result["action"] == "flag_for_review"
    assert result["requires_human_review"] is True
    assert "valid JSON" in result["reasoning"]


def test_crew_crash_fails_safe_to_review(monkeypatch):
    _patch_no_visual_analysis_call(monkeypatch)
    _patch_crew(monkeypatch, RuntimeError("LLM provider timed out"))

    result = agent_pipeline.process_dispute(
        dispute_id="d4",
        reason_code="product_not_received",
        customer_id="cust_4",
        order_id="order_4",
    )

    assert result["action"] == "flag_for_review"
    assert result["requires_human_review"] is True
    assert "currently unavailable" in result["reasoning"]
    assert "timed out" not in result["reasoning"]


def test_unrecognized_action_value_fails_safe_to_review(monkeypatch):
    _patch_no_visual_analysis_call(monkeypatch)
    _patch_crew(
        monkeypatch,
        json.dumps({"action": "maybe_submit_idk", "reasoning": "not sure", "evidence_summary": "meh"}),
    )

    result = agent_pipeline.process_dispute(
        dispute_id="d5",
        reason_code="product_not_received",
        customer_id="cust_5",
        order_id="order_5",
    )

    assert result["action"] == "flag_for_review"
    assert result["requires_human_review"] is True
    assert "unrecognized action" in result["human_review_reason"].lower()


def test_visual_analysis_crash_fails_safe_to_review(monkeypatch):
    # If analyze_evidence_images itself blows up, that must route to human
    # review too, not silently proceed as if no visual evidence existed.
    def _boom(**kwargs):
        raise RuntimeError("Gemini vision call timed out")

    monkeypatch.setattr(agent_pipeline, "analyze_evidence_images", _boom)
    _patch_crew(
        monkeypatch,
        json.dumps({"action": "auto_submit", "reasoning": "fine", "evidence_summary": "fine"}),
    )

    result = agent_pipeline.process_dispute(
        dispute_id="d6",
        reason_code="not_as_described",
        customer_id="cust_6",
        order_id="order_6",
        customer_image_url="https://example.com/photo.jpg",
    )

    assert result["action"] == "flag_for_review"
    assert "currently unavailable" in result["human_review_reason"]
    assert "timed out" not in result["human_review_reason"]


def test_ordinary_markdown_fenced_json_is_still_parsed(monkeypatch):
    # LLMs frequently wrap JSON in ```json fences despite being told not
    # to - the pipeline strips those before parsing.
    _patch_no_visual_analysis_call(monkeypatch)
    _patch_crew(
        monkeypatch,
        '```json\n{"action": "flag_for_review", "reasoning": "ambiguous", "evidence_summary": "mixed"}\n```',
    )

    result = agent_pipeline.process_dispute(
        dispute_id="d7",
        reason_code="fraudulent",
        customer_id="cust_7",
        order_id="order_7",
    )

    assert result["action"] == "flag_for_review"


# --- process_refund_claim() --------------------------------------------

def test_refund_claim_visual_veto_overrides_llm_approval(monkeypatch):
    monkeypatch.setattr(
        agent_pipeline,
        "analyze_evidence_images",
        lambda **kwargs: {
            "requires_human_review": True,
            "human_review_reason": "AI-generation suspected in customer photo.",
            "ai_generated_suspected": True,
        },
    )
    _patch_crew(
        monkeypatch,
        json.dumps({"action": "approve_refund", "reasoning": "photo supports claim", "evidence_summary": "ok"}),
    )

    result = agent_pipeline.process_refund_claim(
        dispute_id="c1",
        reason_code="not_as_described",
        customer_id="user_1",
        order_id="order_1",
        customer_image_url="https://example.com/photo.jpg",
    )

    assert result["action"] == "flag_for_review"
    assert result["requires_human_review"] is True
    assert "AI-generation" in result["human_review_reason"]


def test_refund_claim_unrecognized_action_fails_safe(monkeypatch):
    _patch_no_visual_analysis_call(monkeypatch)
    _patch_crew(
        monkeypatch,
        json.dumps({"action": "give_them_money", "reasoning": "seems nice", "evidence_summary": ""}),
    )

    result = agent_pipeline.process_refund_claim(
        dispute_id="c2",
        reason_code="product_not_received",
        customer_id="user_2",
        order_id="order_2",
    )

    assert result["action"] == "flag_for_review"
    assert result["requires_human_review"] is True


def test_refund_claim_reject_is_a_valid_terminal_action(monkeypatch):
    _patch_no_visual_analysis_call(monkeypatch)
    _patch_crew(
        monkeypatch,
        json.dumps(
            {"action": "reject_claim", "reasoning": "delivery confirmed at address", "evidence_summary": "signed"}
        ),
    )

    result = agent_pipeline.process_refund_claim(
        dispute_id="c3",
        reason_code="product_not_received",
        customer_id="user_3",
        order_id="order_3",
    )

    assert result["action"] == "reject_claim"
    assert result["requires_human_review"] is False


# --- reason_codes.yaml helpers (no mocking needed - pure functions) ---

def test_visual_evidence_required_for_not_as_described():
    assert agent_pipeline._needs_visual_evidence("not_as_described") is True


def test_visual_evidence_not_required_for_product_not_received():
    assert agent_pipeline._needs_visual_evidence("product_not_received") is False


def test_unmapped_reason_code_has_no_required_evidence():
    assert agent_pipeline._required_evidence_for("totally_made_up_code") == []
    assert agent_pipeline._needs_visual_evidence("totally_made_up_code") is False


def test_known_reason_codes_match_yaml_shape():
    assert agent_pipeline._required_evidence_for("product_not_received") == [
        "shipping_proof",
        "delivery_confirmation",
    ]
    assert agent_pipeline._required_evidence_for("fraudulent") == ["crm_logs", "delivery_confirmation"]
