# API Documentation

Complete reference for all Chargeback Responder API endpoints.

## Table of Contents

- [Authentication](#authentication)
- [Base URL](#base-url)
- [Merchant Endpoints](#merchant-endpoints)
- [Customer Endpoints](#customer-endpoints)
- [Public Endpoints](#public-endpoints)
- [Webhook Endpoints](#webhook-endpoints)
- [Error Handling](#error-handling)
- [Examples](#examples)

## Authentication

### Bearer Token (Merchants)

Use the `X-Merchant-Token` header for merchant authentication:

```bash
curl -H "X-Merchant-Token: your_merchant_token" \
  http://localhost:8000/disputes
```

All merchant endpoints require this header.

### Customer Bearer Token

Customers receive a token after signup. Use in `Authorization` header:

```bash
curl -H "Authorization: Bearer customer_token" \
  http://localhost:8000/orders
```

## Base URL

- **Local Development**: `http://localhost:8000`
- **Deployed URL**: Not hosting currently

All examples use `http://localhost:8000`. 

---

## Merchant Endpoints

Endpoints for merchants to view and manage disputes.

### List Disputes

**GET** `/disputes`

List all incoming disputes with optional filtering.

**Headers**:
```
X-Merchant-Token: your_merchant_token
```

**Query Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `skip` | integer | Number of disputes to skip (default: 0) |
| `limit` | integer | Max disputes to return (default: 20) |
| `status` | string | Filter by status (pending, evaluating, approved, rejected) |
| `source` | string | Filter by source (bank_webhook, customer_claim) |

**Request**:
```bash
curl -X GET "http://localhost:8000/disputes?skip=0&limit=10&status=pending" \
  -H "X-Merchant-Token: demo_merchant_token"
```

**Response** (200 OK):
```json
{
  "disputes": [
    {
      "id": "dispute_123",
      "order_id": "order_456",
      "customer_id": "customer_789",
      "reason_code": "chargeback",
      "source": "bank_webhook",
      "status": "pending",
      "deadline": "2026-09-12T10:30:00Z",
      "claim_details": "Unauthorized transaction",
      "evidence_json": {
        "image_data": "base64_encoded_image",
        "mime_type": "image/png"
      },
      "submission_result": {
        "decision": "flag_for_review",
        "confidence": 0.45,
        "reasoning": "Insufficient evidence to auto-contest"
      },
      "requires_human_review": true,
      "created_at": "2026-09-05T10:30:00Z",
      "resolved_at": null
    }
  ],
  "total": 42
}
```

---

### Get Dispute Details

**GET** `/disputes/{dispute_id}`

Retrieve full details of a specific dispute including AI analysis.

**Headers**:
```
X-Merchant-Token: your_merchant_token
```

**Request**:
```bash
curl -X GET "http://localhost:8000/disputes/dispute_123" \
  -H "X-Merchant-Token: demo_merchant_token"
```

**Response** (200 OK):
```json
{
  "id": "dispute_123",
  "order_id": "order_456",
  "customer_id": "customer_789",
  "reason_code": "product_not_received",
  "source": "bank_webhook",
  "status": "evaluating",
  "deadline": "2026-09-12T10:30:00Z",
  "claim_details": "Product not delivered to address",
  "evidence_json": {
    "image_data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "mime_type": "image/png"
  },
  "submission_result": {
    "decision": "auto_submit",
    "confidence": 0.92,
    "reasoning": "Strong shipping evidence with signature confirmation. Recommend contest.",
    "evidence_analysis": {
      "image_authenticity": 0.95,
      "relevance_score": 0.88,
      "anomalies": []
    },
    "agent_analysis": {
      "analyst_findings": "Shipping confirmation found with delivery attempt.",
      "strategist_recommendation": "Submit contest via Razorpay"
    }
  },
  "requires_human_review": false,
  "created_at": "2026-09-05T10:30:00Z",
  "resolved_at": null
}
```

**Error Response** (404 Not Found):
```json
{
  "detail": "Dispute not found"
}
```

---

### Manual Override

**POST** `/disputes/{dispute_id}/review`

Override the AI decision with a manual review decision.

**Headers**:
```
X-Merchant-Token: your_merchant_token
Content-Type: application/json
```

**Request Body**:
```json
{
  "decision": "auto_submit",
  "message": "Merchant approved manual review. Strong shipping evidence supports contest."
}
```

**Query Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `decision` | string | override decision (auto_submit, flag_for_review, reject) |
| `message` | string | Reason for override (max 2000 chars) |

**Request**:
```bash
curl -X POST "http://localhost:8000/disputes/dispute_123/review" \
  -H "X-Merchant-Token: demo_merchant_token" \
  -H "Content-Type: application/json" \
  -d '{
    "decision": "auto_submit",
    "message": "Strong evidence provided. Recommend automatic contest."
  }'
```

**Response** (200 OK):
```json
{
  "id": "dispute_123",
  "status": "manually_contested",
  "message": "Strong evidence provided. Recommend automatic contest.",
  "submission_result": {
    "decision": "auto_submit",
    "overridden": true,
    "override_reason": "Strong evidence provided. Recommend automatic contest.",
    "submitted_by": "merchant"
  }
}
```

**Error Response** (400 Bad Request):
```json
{
  "detail": "Invalid decision. Must be one of: auto_submit, flag_for_review, reject"
}
```

---

## Customer Endpoints

Endpoints for customers to create accounts, orders, and file refund claims.

### Sign Up

**POST** `/auth/signup`

Create a new customer account.

**Headers**:
```
Content-Type: application/json
```

**Request Body**:
```json
{
  "email": "customer@example.com"
}
```

**Request**:
```bash
curl -X POST "http://localhost:8000/auth/signup" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "john@example.com"
  }'
```

**Response** (201 Created):
```json
{
  "user_id": "user_abc123",
  "email": "john@example.com",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "message": "Account created successfully. Save your token for future requests."
}
```

**Error Response** (400 Bad Request):
```json
{
  "detail": "Invalid email format"
}
```

---

### Create Order

**POST** `/orders`

Create a new payment order.

**Headers**:
```
Authorization: Bearer customer_token
Content-Type: application/json
```

**Request Body**:
```json
{
  "amount": 10000,
  "currency": "INR",
  "description": "Premium subscription - yearly"
}
```

**Request**:
```bash
curl -X POST "http://localhost:8000/orders" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 10000,
    "currency": "INR",
    "description": "Premium subscription"
  }'
```

**Response** (201 Created):
```json
{
  "order_id": "order_xyz789",
  "amount": 10000,
  "currency": "INR",
  "status": "pending",
  "razorpay_order_id": "order_1A2b3C4d5E6f7g",
  "description": "Premium subscription",
  "created_at": "2026-09-05T10:30:00Z"
}
```

---

### List Customer Orders

**GET** `/orders`

Retrieve all orders for the authenticated customer.

**Headers**:
```
Authorization: Bearer customer_token
```

**Query Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `skip` | integer | Number of orders to skip (default: 0) |
| `limit` | integer | Max orders to return (default: 20) |

**Request**:
```bash
curl -X GET "http://localhost:8000/orders?skip=0&limit=10" \
  -H "Authorization: Bearer customer_token"
```

**Response** (200 OK):
```json
{
  "orders": [
    {
      "order_id": "order_xyz789",
      "amount": 10000,
      "currency": "INR",
      "status": "paid",
      "created_at": "2026-09-05T10:30:00Z"
    }
  ],
  "total": 5
}
```

---

### Verify Payment

**POST** `/orders/{order_id}/verify-payment`

Confirm Razorpay payment success after checkout.

**Headers**:
```
Authorization: Bearer customer_token
Content-Type: application/json
```

**Request Body**:
```json
{
  "razorpay_payment_id": "pay_1BmP1ZIHYHmMMI",
  "razorpay_signature": "9ef4dffbfd84f1318f6739a3ce19f9d85851857ae648f114332d8401e0949a3d"
}
```

**Request**:
```bash
curl -X POST "http://localhost:8000/orders/order_xyz789/verify-payment" \
  -H "Authorization: Bearer customer_token" \
  -H "Content-Type: application/json" \
  -d '{
    "razorpay_payment_id": "pay_1BmP1ZIHYHmMMI",
    "razorpay_signature": "9ef4dffbfd84f1318f6739a3ce19f9d85851857ae648f114332d8401e0949a3d"
  }'
```

**Response** (200 OK):
```json
{
  "order_id": "order_xyz789",
  "status": "paid",
  "message": "Payment verified successfully"
}
```

**Error Response** (400 Bad Request):
```json
{
  "detail": "Invalid payment signature"
}
```

---

### File Refund Claim

**POST** `/disputes/claim`

File a refund claim with evidence image.

**Headers**:
```
Authorization: Bearer customer_token
Content-Type: application/json
```

**Request Body**:
```json
{
  "order_id": "order_xyz789",
  "reason_code": "product_not_received",
  "claim_details": "Product not delivered to my address despite tracking confirmation",
  "evidence_image": {
    "data": "base64_encoded_image_data",
    "mime_type": "image/png"
  }
}
```

**Request**:
```bash
curl -X POST "http://localhost:8000/disputes/claim" \
  -H "Authorization: Bearer customer_token" \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "order_xyz789",
    "reason_code": "product_not_received",
    "claim_details": "Never received package",
    "evidence_image": {
      "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
      "mime_type": "image/png"
    }
  }'
```

**Response** (201 Created):
```json
{
  "claim_id": "claim_abc123",
  "order_id": "order_xyz789",
  "status": "evaluating",
  "reason_code": "product_not_received",
  "submission_result": {
    "decision": "approve_refund",
    "confidence": 0.88,
    "reasoning": "Strong evidence of non-delivery. Recommend refund approval."
  },
  "message": "Claim submitted. Decision: approve_refund. Refund processing..."
}
```

**Error Response** (400 Bad Request):
```json
{
  "detail": "Order not found or already has a pending claim"
}
```

---

## Public Endpoints

Endpoints available without authentication.

### Health Check

**GET** `/health`

Check if the API is running.

**Request**:
```bash
curl http://localhost:8000/health
```

**Response** (200 OK):
```json
{
  "status": "ok"
}
```

---

## Webhook Endpoints

### Razorpay Webhook

**POST** `/webhook`

Receive Razorpay dispute notifications. This endpoint is called by Razorpay servers.

**Headers**:
```
X-Razorpay-Signature: signature_from_razorpay
Content-Type: application/json
```

**Webhook Body** (example dispute):
```json
{
  "event": "dispute.created",
  "created_at": 1694000000,
  "entity": "event",
  "payload": {
    "dispute": {
      "id": "disp_1234567890",
      "entity": "dispute",
      "payment_id": "pay_1BmP1ZIHYHmMMI",
      "amount": 10000,
      "currency": "INR",
      "amount_deducted": 0,
      "reason_code": "chargeback",
      "respond_by": 1694500000,
      "status": "open",
      "phase": "chargeback",
      "created_at": 1694000000,
      "evidence": {
        "amount": 10000,
        "summary": "Proof of Delivery",
        "submitted_at": null,
        "dispute_evidence": []
      },
      "notes": {}
    }
  }
}
```

**Note**: This is a server-to-server callback. Configure the webhook URL in Razorpay dashboard:
- Use your deployed public URL when hosting the app
- Local Testing: Use ngrok (`ngrok http 8000`) to expose local server

---

## Error Handling

### Error Response Format

All errors return a JSON response with HTTP status code:

```json
{
  "detail": "Error message describing what went wrong"
}
```

### HTTP Status Codes

| Code | Meaning | Example |
|------|---------|---------|
| 200 | OK | Request successful |
| 201 | Created | Resource created (dispute, order, etc.) |
| 400 | Bad Request | Invalid input or malformed JSON |
| 401 | Unauthorized | Missing or invalid authentication token |
| 404 | Not Found | Resource doesn't exist |
| 409 | Conflict | Duplicate entry or state conflict |
| 500 | Server Error | Internal server error |

### Common Error Scenarios

**Missing Authentication**:
```bash
curl http://localhost:8000/disputes
```
Response (401):
```json
{
  "detail": "Missing X-Merchant-Token header"
}
```

**Invalid Token**:
```bash
curl -H "X-Merchant-Token: invalid_token" http://localhost:8000/disputes
```
Response (401):
```json
{
  "detail": "Invalid merchant token"
}
```

**Resource Not Found**:
```bash
curl -H "X-Merchant-Token: demo_merchant_token" \
  http://localhost:8000/disputes/nonexistent_id
```
Response (404):
```json
{
  "detail": "Dispute not found"
}
```

---

## Examples

### Complete Workflow: Merchant Review Dispute

```bash
# Step 1: Get merchant token (from environment)
MERCHANT_TOKEN="demo_merchant_token"
BASE_URL="http://localhost:8000"

# Step 2: List all pending disputes
curl -X GET "$BASE_URL/disputes?status=pending" \
  -H "X-Merchant-Token: $MERCHANT_TOKEN"

# Step 3: Get details of specific dispute
DISPUTE_ID="dispute_123"
curl -X GET "$BASE_URL/disputes/$DISPUTE_ID" \
  -H "X-Merchant-Token: $MERCHANT_TOKEN"

# Step 4: Review AI recommendation and override if needed
curl -X POST "$BASE_URL/disputes/$DISPUTE_ID/review" \
  -H "X-Merchant-Token: $MERCHANT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "decision": "auto_submit",
    "message": "Merchant reviewed shipping evidence. Approves auto-submit."
  }'
```

### Complete Workflow: Customer Refund Claim

```bash
BASE_URL="http://localhost:8000"

# Step 1: Sign up
SIGNUP=$(curl -X POST "$BASE_URL/auth/signup" \
  -H "Content-Type: application/json" \
  -d '{"email": "customer@example.com"}')

CUSTOMER_TOKEN=$(echo $SIGNUP | jq -r '.token')
USER_ID=$(echo $SIGNUP | jq -r '.user_id')
echo "Token: $CUSTOMER_TOKEN"

# Step 2: Create order
ORDER=$(curl -X POST "$BASE_URL/orders" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 5000,
    "currency": "INR",
    "description": "Test product"
  }')

ORDER_ID=$(echo $ORDER | jq -r '.order_id')
RAZORPAY_ORDER_ID=$(echo $ORDER | jq -r '.razorpay_order_id')
echo "Order ID: $ORDER_ID"

# Step 3: Complete payment (use Razorpay Checkout SDK in frontend)
# After payment, receive razorpay_payment_id and razorpay_signature

# Step 4: Verify payment
curl -X POST "$BASE_URL/orders/$ORDER_ID/verify-payment" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "razorpay_payment_id": "pay_1BmP1ZIHYHmMMI",
    "razorpay_signature": "9ef4dffbfd84f1318f6739a3ce19f9d85851857ae648f114332d8401e0949a3d"
  }'

# Step 5: File refund claim (if needed)
curl -X POST "$BASE_URL/disputes/claim" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "'$ORDER_ID'",
    "reason_code": "product_not_received",
    "claim_details": "Product was not delivered",
    "evidence_image": {
      "data": "base64_image_data",
      "mime_type": "image/png"
    }
  }'
```

---

## Rate Limiting

Currently not implemented. See [Roadmap](ROADMAP.md) for planned rate limiting.

## Pagination

List endpoints support pagination:

```bash
# Get first 10 results
curl "$BASE_URL/disputes?skip=0&limit=10"

# Get next 10 results
curl "$BASE_URL/disputes?skip=10&limit=10"

# Get all (no limit)
curl "$BASE_URL/disputes"
```

---

For implementation examples, see `backend/tests/test_main_api.py` and `frontend/src/api.js`.
