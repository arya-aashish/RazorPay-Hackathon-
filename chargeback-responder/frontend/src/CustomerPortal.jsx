import { useEffect, useState, useCallback } from "react";
import { signup, createOrder, listOrders, verifyPayment, fileClaim, ApiError } from "./api";
import { openRazorpayCheckout } from "./razorpayCheckout";

const REASON_CODES = [
  { value: "product_not_received", label: "Product not received" },
  { value: "duplicate_processing", label: "Charged twice" },
  { value: "not_as_described", label: "Item not as described (e.g. wrong color)" },
  { value: "fraudulent", label: "I didn't make this purchase" },
  { value: "other", label: "Other" },
];

const PRODUCT_COLORS = ["Black", "White", "Red", "Blue", "Navy blue", "Green", "Yellow", "Pink", "Purple", "Brown", "Grey"];

export default function CustomerPortal() {
  const [apiToken, setApiToken] = useState(() => localStorage.getItem("customer_api_token") || "");
  const [email, setEmail] = useState("");
  const [orders, setOrders] = useState([]);
  const [amount, setAmount] = useState("499.00");
  const [productColor, setProductColor] = useState(PRODUCT_COLORS[0]);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  const [claimOrderId, setClaimOrderId] = useState("");
  const [claimReason, setClaimReason] = useState(REASON_CODES[0].value);
  const [claimDetails, setClaimDetails] = useState("");
  const [claimImageData, setClaimImageData] = useState("");
  const [claimImageName, setClaimImageName] = useState("");

  useEffect(() => {
    if (apiToken) localStorage.setItem("customer_api_token", apiToken);
  }, [apiToken]);

  const refreshOrders = useCallback(async () => {
    if (!apiToken) return;
    try {
      setOrders(await listOrders(apiToken));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        // Expired credentials are deliberately unusable. Clear the local
        // copy so the portal does not keep retrying a dead session.
        localStorage.removeItem("customer_api_token");
        setApiToken("");
        setOrders([]);
      }
      setMessage({ tone: "danger", text: err instanceof ApiError ? err.message : "Could not load orders." });
    }
  }, [apiToken]);

  useEffect(() => {
    refreshOrders();
  }, [refreshOrders]);

  // Merchant decisions are made in the other portal, so keep the buyer's
  // status current without requiring a manual reload.
  useEffect(() => {
    if (!apiToken) return undefined;
    const timer = setInterval(refreshOrders, 5000);
    return () => clearInterval(timer);
  }, [apiToken, refreshOrders]);

  const handleSignup = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const res = await signup(email);
      setApiToken(res.api_token);
      setMessage({ tone: "ok", text: `Signed up as ${res.email}. Your session token is saved in this browser.` });
    } catch (err) {
      setMessage({ tone: "danger", text: err instanceof ApiError ? err.message : "Signup failed." });
    } finally {
      setBusy(false);
    }
  };

  const handleLogOut = () => {
    localStorage.removeItem("customer_api_token");
    setApiToken("");
    setOrders([]);
  };

  const handleBuy = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const paise = Math.round(parseFloat(amount) * 100);
      const order = await createOrder(apiToken, paise, "INR", productColor);
      const rzpResponse = await openRazorpayCheckout({
        orderId: order.order_id,
        amount: paise,
        currency: order.currency,
        keyId: order.razorpay_key_id,
        description: "Chargeback Responder demo purchase",
      });
      await verifyPayment(apiToken, order.order_id, rzpResponse);
      setMessage({ tone: "ok", text: `Payment confirmed for order ${order.order_id} (${productColor}).` });
      refreshOrders();
    } catch (err) {
      setMessage({ tone: "danger", text: err instanceof ApiError ? err.message : err.message || "Purchase failed." });
    } finally {
      setBusy(false);
    }
  };

  const handleFileClaim = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const res = await fileClaim(apiToken, {
        orderId: claimOrderId,
        reasonCode: claimReason,
        claimDetails,
        evidenceImageData: claimImageData,
      });
      setMessage({ tone: "ok", text: `Claim filed (${res.dispute_id}). Check the Merchant Dashboard tab to watch it get adjudicated.` });
      setClaimDetails("");
      setClaimImageData("");
      setClaimImageName("");
      refreshOrders();
    } catch (err) {
      setMessage({ tone: "danger", text: err instanceof ApiError ? err.message : "Filing the claim failed." });
    } finally {
      setBusy(false);
    }
  };

  const paidOrders = orders.filter((o) => o.status === "paid");

  return (
    <div className="portal">
      <div className="portal__inner">
        <h2>Customer portal</h2>
        <p className="portal__intro">
          This simulates a real shopper: sign up, make a real Razorpay Test Mode purchase, then
          file a refund claim the same way a customer would. The AI pipeline adjudicates it in the
          background — watch it resolve on the Merchant Dashboard tab.
        </p>

        {message ? <div className={`error-banner`} style={message.tone === "ok" ? { background: "var(--ok-soft)", color: "var(--ok)", borderColor: "var(--ok)" } : undefined}>{message.text}</div> : null}

        {!apiToken ? (
          <div className="card">
            <h3>Sign up</h3>
            <div className="field">
              <label>Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
            </div>
            <button className="btn btn--approve" disabled={busy || !email} onClick={handleSignup}>
              Create account
            </button>
          </div>
        ) : (
          <>
            <div className="session-line">
              <span>Signed in — token <strong>{apiToken.slice(0, 10)}…</strong></span>
              <button className="link-btn" onClick={handleLogOut}>Log out</button>
            </div>

            <div className="card">
              <h3>Make a test purchase</h3>
              <div className="field-row">
                <div className="field">
                  <label>Amount (INR)</label>
                  <input value={amount} onChange={(e) => setAmount(e.target.value)} />
                </div>
                <div className="field">
                  <label>Product color</label>
                  <select value={productColor} onChange={(e) => setProductColor(e.target.value)}>
                    {PRODUCT_COLORS.map((color) => <option key={color} value={color}>{color}</option>)}
                  </select>
                </div>
              </div>
              <button className="btn btn--approve" disabled={busy} onClick={handleBuy}>
                Buy &amp; pay with Razorpay
              </button>
              <p className="empty-note" style={{ marginTop: 10 }}>
                Opens real Razorpay Test Mode checkout. Use test card 4111 1111 1111 1111, any future expiry/CVV.
              </p>
            </div>

            <div className="card">
              <h3>Your orders</h3>
              {orders.length === 0 ? (
                <p className="empty-note">No orders yet.</p>
              ) : (
                orders.map((o) => (
                  <div className="order-row" key={o.order_id}>
                    <span className="order-row__id">{o.order_id}</span>
                    <span>{(o.amount / 100).toFixed(2)} {o.currency}</span>
                    {o.product_color ? <span>{o.product_color}</span> : null}
                    <span className={`badge badge--${o.claim_status === "approve_refund" ? "ok" : o.claim_status === "reject_claim" ? "danger" : o.claim_status ? "warn" : o.status === "paid" ? "ok" : "neutral"}`}>
                      {o.claim_status === "approve_refund" ? "refund sent to bank" : o.claim_status === "reject_claim" ? "claim denied" : o.claim_status ? o.claim_status.replaceAll("_", " ") : o.status}
                    </span>
                    {o.claim_resolved_at ? <span className="order-row__time">Updated {new Date(o.claim_resolved_at).toLocaleString()}</span> : null}
                    {o.claim_merchant_message ? <p className="order-row__message"><strong>Merchant reply:</strong> {o.claim_merchant_message}</p> : null}
                  </div>
                ))
              )}
            </div>

            <div className="card">
              <h3>File a refund claim</h3>
              <div className="field">
                <label>Which order</label>
                <select value={claimOrderId} onChange={(e) => setClaimOrderId(e.target.value)}>
                  <option value="">Select a paid order…</option>
                  {paidOrders.map((o) => (
                    <option key={o.order_id} value={o.order_id}>
                      {o.order_id} — {(o.amount / 100).toFixed(2)} {o.currency}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Reason</label>
                <select value={claimReason} onChange={(e) => setClaimReason(e.target.value)}>
                  {REASON_CODES.map((r) => (
                    <option key={r.value} value={r.value}>{r.label}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>{claimReason === "other" ? "Describe your reason" : "Tell us what happened"}</label>
                <textarea
                  value={claimDetails}
                  onChange={(e) => setClaimDetails(e.target.value)}
                  placeholder={claimReason === "other" ? "Describe the issue and the resolution you are requesting." : "e.g. Item arrived in the wrong color — I ordered navy blue but received black."}
                />
              </div>
              <div className="field">
                <label>Evidence photo (optional)</label>
                <input
                  type="file"
                  accept="image/*"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    if (file.size > 8 * 1024 * 1024) {
                      setMessage({ tone: "danger", text: "Evidence images must be 8 MB or smaller." });
                      e.target.value = "";
                      return;
                    }
                    const reader = new FileReader();
                    reader.onload = () => setClaimImageData(String(reader.result));
                    reader.readAsDataURL(file);
                    setClaimImageName(file.name);
                  }}
                />
                {claimImageName ? <p className="empty-note">Attached: {claimImageName}</p> : null}
              </div>
              <button className="btn btn--reject" disabled={busy || !claimOrderId || !claimDetails} onClick={handleFileClaim}>
                Submit claim
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
