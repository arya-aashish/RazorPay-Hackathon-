const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, { method = "GET", body, headers = {} } = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  let payload = null;
  const text = await res.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!res.ok) {
    const detail = (payload && payload.detail) || res.statusText;
    throw new ApiError(detail, res.status, payload);
  }
  return payload;
}

// ---- Merchant dashboard (X-Merchant-Token header) ----

export function fetchDisputes(merchantToken) {
  return request("/disputes", { headers: { "X-Merchant-Token": merchantToken } });
}

export function fetchDispute(merchantToken, disputeId) {
  return request(`/disputes/${disputeId}`, { headers: { "X-Merchant-Token": merchantToken } });
}

export function reviewDispute(merchantToken, disputeId, action, message) {
  return request(`/disputes/${disputeId}/review`, {
    method: "POST",
    headers: { "X-Merchant-Token": merchantToken },
    body: { action, message },
  });
}

// ---- Customer portal (Bearer token) ----

export function signup(email, name) {
  return request("/auth/signup", { method: "POST", body: { email, name } });
}

export function createOrder(apiToken, amount, currency = "INR") {
  return request("/orders", {
    method: "POST",
    headers: { Authorization: `Bearer ${apiToken}` },
    body: { amount, currency },
  });
}

export function listOrders(apiToken) {
  return request("/orders", { headers: { Authorization: `Bearer ${apiToken}` } });
}

export function verifyPayment(apiToken, orderId, razorpayResponse) {
  return request(`/orders/${orderId}/verify-payment`, {
    method: "POST",
    headers: { Authorization: `Bearer ${apiToken}` },
    body: {
      razorpay_order_id: razorpayResponse.razorpay_order_id,
      razorpay_payment_id: razorpayResponse.razorpay_payment_id,
      razorpay_signature: razorpayResponse.razorpay_signature,
    },
  });
}

export function fileClaim(apiToken, { orderId, reasonCode, claimDetails, evidenceImageData }) {
  return request("/disputes/claim", {
    method: "POST",
    headers: { Authorization: `Bearer ${apiToken}` },
    body: {
      order_id: orderId,
      reason_code: reasonCode,
      claim_details: claimDetails,
      evidence_image_data: evidenceImageData || null,
    },
  });
}

export { ApiError, API_BASE };
