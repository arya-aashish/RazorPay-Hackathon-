"""
Held-out evaluation for the chargeback evidence responder.

This is what the AI Risk Manager track's grading bar explicitly asks for:
"measured precision and recall on a held-out test set" and "honest metrics
including false-positive cost." Before this file, that measurement did not
exist anywhere in the project - decisions were made but never scored
against ground truth.

Framing: treat "auto_submit" as the positive class (the model asserting
"I'm confident enough to act autonomously"). In this domain:
  - False positive  = auto_submit when the correct call was flag_for_review.
    This is the expensive mistake: it means evidence went to Razorpay
    without human sign-off on a case that needed it - e.g. genuinely
    fraudulent/AI-generated evidence, or a weak case that a human would
    have caught. Cost modeled explicitly below, not just counted.
  - False negative  = flag_for_review when auto_submit was actually safe.
    Cheaper mistake: costs analyst time, not money/credibility, but still
    undermines the "automate this" pitch if it happens often.

Run with: python -m app.eval_test_set
(from the backend/ directory, with a real .env and valid API keys - this
makes live LLM/vision calls, it is not free/instant.)

NOTE ON THE TEST SET BELOW: 10 cases is a starting point, not a finished
benchmark - it exists so there's a real, reproducible number to report by
Saturday instead of no number at all. Expand this as time allows; each
case's `expected_action` is the human-judged correct answer, i.e. ground
truth this script checks the pipeline against.
"""

import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from .agent_pipeline import process_dispute


@dataclass
class TestCase:
    name: str
    dispute_id: str
    reason_code: str
    customer_id: str
    order_id: str
    claim_details: str
    customer_image_url: Optional[str]
    expected_action: str  # "auto_submit" or "flag_for_review" - ground truth
    # Optional: estimated $ cost if this case is gotten WRONG in the
    # false-positive direction (wrongly auto-submitted). Fill in with real
    # merchant numbers if available; placeholder values below are for
    # illustration only - swap for actual average dispute amounts.
    false_positive_cost_usd: float = 50.0


# --- Held-out test set -------------------------------------------------
# Mix of: clear-cut auto_submit cases, clear-cut flag_for_review cases,
# and deliberately ambiguous/adversarial cases (the ones that matter most
# for an honest precision/recall number).
TEST_CASES = [
    TestCase(
        name="Clear delivery proof, no image needed",
        dispute_id="eval_001",
        reason_code="product_not_received",
        customer_id="eval-customer-1@example.com",
        order_id="eval_order_1",
        claim_details="Customer says item never arrived.",
        customer_image_url=None,
        expected_action="auto_submit",  # strong shipping+delivery evidence should suffice
    ),
    TestCase(
        name="Wrong color claim, image genuinely shows mismatch",
        dispute_id="eval_002",
        reason_code="not_as_described",
        customer_id="eval-customer-2@example.com",
        order_id="eval_order_2",
        claim_details="Item arrived in the wrong color - ordered navy blue, received black.",
        customer_image_url="https://dummyimage.com/600x600/1a1a1a/ffffff.png&text=Black+Received",
        expected_action="flag_for_review",  # legitimate mismatch -> should NOT be auto-contested
        false_positive_cost_usd=75.0,
    ),
    TestCase(
        name="Wrong color claim, image actually matches order (weak claim)",
        dispute_id="eval_003",
        reason_code="not_as_described",
        customer_id="eval-customer-3@example.com",
        order_id="eval_order_3",
        claim_details="Item arrived in the wrong color - ordered navy blue, received black.",
        customer_image_url="https://dummyimage.com/600x600/1a3d7c/ffffff.png&text=Navy+Received",
        expected_action="auto_submit",  # claim contradicted by own evidence
        false_positive_cost_usd=75.0,
    ),
    TestCase(
        name="Duplicate processing, weak CRM evidence",
        dispute_id="eval_004",
        reason_code="duplicate_processing",
        customer_id="eval-customer-4@example.com",
        order_id="eval_order_4",
        claim_details="Customer says they were charged twice.",
        customer_image_url=None,
        expected_action="flag_for_review",
        false_positive_cost_usd=40.0,
    ),
    TestCase(
        name="Fraudulent reason code, ambiguous",
        dispute_id="eval_005",
        reason_code="fraudulent",
        customer_id="eval-customer-5@example.com",
        order_id="eval_order_5",
        claim_details="Customer claims they never made this purchase.",
        customer_image_url=None,
        expected_action="flag_for_review",  # fraud claims should almost always go to a human
        false_positive_cost_usd=150.0,
    ),
    TestCase(
        name="Duplicate processing, strong CRM evidence supports contesting",
        dispute_id="eval_006",
        reason_code="duplicate_processing",
        customer_id="eval-customer-6@example.com",
        order_id="eval_order_6",
        claim_details="Customer says they were charged twice for the same order.",
        customer_image_url=None,
        expected_action="auto_submit",  # balances eval_004 - not every duplicate_processing case is weak
        false_positive_cost_usd=40.0,
    ),
    TestCase(
        name="Unmapped/unknown reason code - no evidence policy to lean on",
        dispute_id="eval_007",
        reason_code="unrecognized_code_xyz",
        customer_id="eval-customer-7@example.com",
        order_id="eval_order_7",
        claim_details="Customer's stated reason doesn't match a known category.",
        customer_image_url=None,
        expected_action="flag_for_review",  # no required_evidence mapping -> should not default to confident auto_submit
        false_positive_cost_usd=60.0,
    ),
    TestCase(
        name="Suspected AI-generated/manipulated evidence photo",
        # NOTE: swap this URL for a genuine AI-generated/manipulated test
        # image before reporting real numbers - a placeholder photo won't
        # actually exercise the ai_generated_suspected path in
        # vision_analysis.py the way a real one would.
        dispute_id="eval_008",
        reason_code="not_as_described",
        customer_id="eval-customer-8@example.com",
        order_id="eval_order_8",
        claim_details="Item arrived damaged - photo attached.",
        customer_image_url="https://dummyimage.com/600x600/ff00ff/000000.png&text=SUSPECT+IMAGE",
        expected_action="flag_for_review",  # manipulation/AI-gen suspicion must force human review, never auto_submit
        false_positive_cost_usd=100.0,
    ),
    # --- Add more cases here before Saturday. Aim for at least a few per
    # reason_code, plus 2-3 more deliberately adversarial image cases
    # (e.g. a genuinely AI-generated-looking image) to actually test the
    # AI-generation screen in vision_analysis.py, not just the color check.
]


def run_eval():
    results = []
    for case in TEST_CASES:
        print(f"Running: {case.name} ({case.dispute_id})...")
        start = time.time()
        try:
            outcome = process_dispute(
                dispute_id=case.dispute_id,
                reason_code=case.reason_code,
                customer_id=case.customer_id,
                order_id=case.order_id,
                claim_details=case.claim_details,
                customer_image_url=case.customer_image_url,
            )
        except Exception as exc:
            outcome = {"action": "ERROR", "reasoning": str(exc)}
        elapsed = time.time() - start
        predicted = outcome.get("action", "ERROR")
        results.append(
            {
                "case": case,
                "predicted": predicted,
                "correct": predicted == case.expected_action,
                "elapsed_s": round(elapsed, 1),
                "outcome": outcome,
            }
        )
        print(f"  -> predicted={predicted} expected={case.expected_action} "
              f"({'OK' if predicted == case.expected_action else 'MISMATCH'}) [{elapsed:.1f}s]")

    print_report(results)


def print_report(results):
    # Positive class = auto_submit
    tp = sum(1 for r in results if r["predicted"] == "auto_submit" and r["case"].expected_action == "auto_submit")
    fp = sum(1 for r in results if r["predicted"] == "auto_submit" and r["case"].expected_action != "auto_submit")
    fn = sum(1 for r in results if r["predicted"] != "auto_submit" and r["case"].expected_action == "auto_submit")
    tn = sum(1 for r in results if r["predicted"] != "auto_submit" and r["case"].expected_action != "auto_submit")

    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    accuracy = (tp + tn) / len(results) if results else float("nan")

    false_positive_cases = [r for r in results if r["predicted"] == "auto_submit" and r["case"].expected_action != "auto_submit"]
    total_fp_cost = sum(r["case"].false_positive_cost_usd for r in false_positive_cases)

    print("\n" + "=" * 60)
    print("EVAL REPORT")
    print("=" * 60)
    print(f"n = {len(results)} held-out cases")
    print(f"TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    print(f"Precision (auto_submit): {precision:.2f}" if precision == precision else "Precision: n/a (no positives predicted)")
    print(f"Recall (auto_submit):    {recall:.2f}" if recall == recall else "Recall: n/a (no positive ground truth)")
    print(f"Accuracy:                {accuracy:.2f}")
    print(f"Estimated false-positive cost: ${total_fp_cost:.2f}  "
          f"(sum of false_positive_cost_usd across {fp} FP case(s) - "
          f"replace placeholder $ values with real average dispute amounts)")
    if false_positive_cases:
        print("\nFalse positives (wrongly auto-submitted - the expensive mistake):")
        for r in false_positive_cases:
            print(f"  - {r['case'].name}: {r['outcome'].get('reasoning', '')}")
    print("=" * 60)


if __name__ == "__main__":
    run_eval()
