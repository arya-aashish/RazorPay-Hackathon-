import { useEffect, useState, useCallback } from "react";
import { fetchDisputes, reviewDispute, ApiError } from "./api";

const POLL_MS = 6000;

function statusTone(status, requiresReview) {
  if (requiresReview) return "warn";
  if (["auto_submit", "auto_contested", "approve_refund", "manually_contested"].includes(status)) return "ok";
  if (["action_failed", "reject_claim", "manually_not_contested"].includes(status)) return "danger";
  return "neutral";
}

function StatusBadge({ status, requiresReview, pulse }) {
  const tone = statusTone(status, requiresReview);
  const label = requiresReview ? "needs review" : (status || "pending").replaceAll("_", " ");
  const pulseClass = pulse && requiresReview ? " badge--pulse" : "";
  return <span className={`badge badge--${tone}${pulseClass}`}>{label}</span>;
}

function formatTimestamp(iso) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).format(new Date(iso));
}

function VisualForensics({ visual }) {
  if (!visual) return null;
  const supported = visual.claim_supported;
  const aiSuspected = visual.ai_generated_suspected;
  return (
    <div className="section">
      <h3>Visual forensics</h3>
      <div className="forensics-grid">
        <div className="forensics-card">
          <div className="forensics-card__label">Claim supported by photo</div>
          <div className="forensics-card__value" style={{ color: supported === "yes" ? "var(--ok)" : supported === "no" ? "var(--danger)" : "var(--warn)" }}>
            {supported ?? "n/a"}
          </div>
        </div>
        <div className="forensics-card">
          <div className="forensics-card__label">AI-generated suspected</div>
          <div className="forensics-card__value" style={{ color: aiSuspected ? "var(--danger)" : "var(--ok)" }}>
            {aiSuspected ? "yes" : "no"}
            {typeof visual.ai_generation_confidence === "number" ? ` (${Math.round(visual.ai_generation_confidence * 100)}%)` : ""}
          </div>
        </div>
        <div className="forensics-card">
          <div className="forensics-card__label">Overall confidence</div>
          <div className="forensics-card__value">
            {typeof visual.overall_confidence === "number" ? `${Math.round(visual.overall_confidence * 100)}%` : "n/a"}
          </div>
        </div>
        <div className="forensics-card">
          <div className="forensics-card__label">Requires human review</div>
          <div className="forensics-card__value" style={{ color: visual.requires_human_review ? "var(--warn)" : "var(--ok)" }}>
            {visual.requires_human_review ? "yes" : "no"}
          </div>
        </div>
      </div>
      {visual.claim_reasoning ? (
        <p style={{ fontSize: 13, color: "var(--text-dim)", marginTop: 10 }}>{visual.claim_reasoning}</p>
      ) : null}
    </div>
  );
}

function DisputeDetail({ dispute, onAction, actionState }) {
  const [merchantMessage, setMerchantMessage] = useState("");

  if (!dispute) {
    return (
      <div className="detail">
        <p className="detail__placeholder">Select an entry from the ledger to inspect it.</p>
      </div>
    );
  }

  const result = dispute.submission_result || {};
  const visual = result.visual_evidence;

  return (
    <div className="detail" key={dispute.id}>
      <div className="detail__header">
        <div>
          <h2>{dispute.id}</h2>
          <div style={{ marginTop: 6, display: "flex", gap: 8, alignItems: "center" }}>
            <StatusBadge status={dispute.status} requiresReview={dispute.requires_human_review} pulse />
            <span className="badge badge--neutral">{dispute.source === "customer_claim" ? "customer claim" : "bank webhook"}</span>
          </div>
        </div>
      </div>

      <div className="section">
        <h3>Claim</h3>
        <dl className="kv">
          <dt>Order</dt>
          <dd className="mono">{dispute.order_id || "—"}</dd>
          <dt>Customer</dt>
          <dd className="mono">{dispute.customer_id || "—"}</dd>
          <dt>Reason code</dt>
          <dd className="mono">{dispute.reason_code}</dd>
          <dt>Filed</dt>
          <dd>{formatTimestamp(dispute.created_at)}</dd>
          {dispute.resolved_at ? <><dt>Resolved</dt><dd>{formatTimestamp(dispute.resolved_at)}</dd></> : null}
          {dispute.deadline ? (
            <>
              <dt>Respond by</dt>
              <dd>{new Date(dispute.deadline).toLocaleString()}</dd>
            </>
          ) : null}
        </dl>
        {dispute.claim_details ? <p style={{ marginTop: 10, fontSize: 14 }}>"{dispute.claim_details}"</p> : null}
        {(dispute.customer_evidence_image || dispute.customer_evidence_image_url) ? (
          <img className="evidence-photo" src={dispute.customer_evidence_image || dispute.customer_evidence_image_url} alt="Customer-submitted evidence" />
        ) : null}
      </div>

      <div className="section">
        <h3>Agent decision</h3>
        <dl className="kv">
          <dt>Evidence summary</dt>
          <dd>{result.evidence_summary || "—"}</dd>
          <dt>Reasoning</dt>
          <dd>{result.reasoning || "—"}</dd>
          {dispute.human_review_reason ? (
            <>
              <dt>Review reason</dt>
              <dd style={{ color: "var(--warn)" }}>{dispute.human_review_reason}</dd>
            </>
          ) : null}
        </dl>
      </div>

      <VisualForensics visual={visual} />

      {(result.razorpay_submission || result.razorpay_refund) && (
        <div className="section">
          <h3>Payment outcome</h3>
          <p className="empty-note">
            {result.razorpay_refund
              ? "Refund request passed to the bank for processing."
              : "Dispute response passed to the bank for processing."}
          </p>
        </div>
      )}

      {dispute.requires_human_review && (
        <div className="section">
          <h3>Respond to customer</h3>
          <textarea
            className="notes-input"
            placeholder="Optional message shown to the customer with your decision"
            value={merchantMessage}
            maxLength={2000}
            onChange={(e) => setMerchantMessage(e.target.value)}
          />
          <div className="actions">
            <button
              className="btn btn--approve"
              disabled={actionState === "loading"}
              onClick={() => onAction(dispute.id, "approve", merchantMessage)}
            >
              {dispute.source === "customer_claim" ? "Approve refund" : "Contest dispute"}
            </button>
            <button
              className="btn btn--reject"
              disabled={actionState === "loading"}
              onClick={() => onAction(dispute.id, "reject", merchantMessage)}
            >
              {dispute.source === "customer_claim" ? "Deny claim" : "Don't contest"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function MerchantDashboard({ merchantToken, setMerchantToken }) {
  const [disputes, setDisputes] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [error, setError] = useState(null);
  const [actionState, setActionState] = useState(null);

  const load = useCallback(async () => {
    if (!merchantToken) return;
    try {
      const data = await fetchDisputes(merchantToken);
      setDisputes(data);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the backend.");
    }
  }, [merchantToken]);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  const selected = disputes.find((d) => d.id === selectedId) || null;

  const handleAction = async (disputeId, action, message) => {
    setActionState("loading");
    try {
      await reviewDispute(merchantToken, disputeId, action, message);
      await load();
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    } finally {
      setActionState(null);
    }
  };

  const needsReview = disputes.filter((d) => d.requires_human_review).length;
  const resolved = disputes.filter((d) => !d.requires_human_review && d.status !== "pending" && d.status !== "evaluating").length;

  return (
    <div className="dashboard">
      <div className="ledger">
        <div className="ledger__stats">
          <div className="stat">
            <div className="stat__value">{disputes.length}</div>
            <div className="stat__label">total</div>
          </div>
          <div className="stat">
            <div className="stat__value" style={{ color: "var(--warn)" }}>{needsReview}</div>
            <div className="stat__label">needs review</div>
          </div>
          <div className="stat">
            <div className="stat__value" style={{ color: "var(--ok)" }}>{resolved}</div>
            <div className="stat__label">resolved</div>
          </div>
          <div className="stat">
            <div className="stat__value">{disputes.filter((d) => d.status === "pending" || d.status === "evaluating").length}</div>
            <div className="stat__label">processing</div>
          </div>
        </div>

        {error ? <div className="error-banner" style={{ margin: 12 }}>{error}</div> : null}

        <div className="ledger__list">
          {disputes.length === 0 && !error ? (
            <p className="ledger__empty">
              No disputes yet. Fire a test webhook or file a claim from the Customer Portal tab to see one appear here.
            </p>
          ) : null}
          {disputes.map((d) => (
            <button
              key={d.id}
              className="ledger-row"
              data-selected={d.id === selectedId}
              data-status={statusTone(d.status, d.requires_human_review)}
              onClick={() => setSelectedId(d.id)}
            >
              <div className="ledger-row__top">
                <span className="ledger-row__id">{d.id}</span>
                <span className="ledger-row__time">{formatTimestamp(d.created_at)}</span>
              </div>
              <div className="ledger-row__reason">{d.reason_code}</div>
              <StatusBadge status={d.status} requiresReview={d.requires_human_review} />
            </button>
          ))}
        </div>
      </div>

      <DisputeDetail key={selected ? selected.id : "none"} dispute={selected} onAction={handleAction} actionState={actionState} />
    </div>
  );
}
