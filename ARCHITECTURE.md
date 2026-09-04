# Architecture Overview

Complete system design documentation for Chargeback Responder.

## Table of Contents

- [System Architecture](#system-architecture)
- [Data Model](#data-model)
- [Component Descriptions](#component-descriptions)
- [Dispute Processing Flow](#dispute-processing-flow)
- [Refund Claim Flow](#refund-claim-flow)
- [Technology Stack](#technology-stack)
- [Security Architecture](#security-architecture)
- [Scalability Considerations](#scalability-considerations)

## System Architecture

### High-Level Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Frontend Layer                              │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  React SPA (Vite)                                            │  │
│  │  ├─ MerchantDashboard.jsx  (Dispute management)             │  │
│  │  └─ CustomerPortal.jsx     (Order + Claim filing)           │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ HTTP/REST API
┌────────────────────────────────▼─────────────────────────────────────┐
│                         API Layer (FastAPI)                         │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Merchant Routes         Customer Routes      Public Routes  │  │
│  │  ├─ GET /disputes        ├─ POST /auth/signup ├─ GET /health
│  │  ├─ GET /disputes/{id}   ├─ POST /orders      │              │
│  │  └─ POST /disputes/{}/review ├─ GET /orders   │              │
│  │                          ├─ POST /verify-payment             │
│  │                          └─ POST /disputes/claim             │
│  │                                               │              │
│  │  Webhook Handler: POST /webhook (Razorpay)    │              │
│  └──────────────────────────────────────────────┬──────────────┘  │
└────────┬─────────────────────────────────────────┼──────────────────┘
         │                                         │
         │                                         │
    ┌────▼────────────────────────────────────────▼────┐
    │                                                   │
    │     Business Logic & Orchestration Layer         │
    │  ┌───────────────────────────────────────────┐  │
    │  │  agent_pipeline.py                        │  │
    │  │  ├─ process_dispute()                     │  │
    │  │  │  └─ CrewAI Analyst + Strategist       │  │
    │  │  └─ process_refund_claim()                │  │
    │  │     └─ CrewAI Adjudication agents        │  │
    │  │                                           │  │
    │  │  vision_analysis.py                      │  │
    │  │  └─ analyze_evidence()                   │  │
    │  │     └─ Gemini Vision API                 │  │
    │  │                                           │  │
    │  │  deadline_scheduler.py                   │  │
    │  │  └─ Background job runner (APScheduler)  │  │
    │  │     └─ Check dispute deadlines           │  │
    │  └───────────────────────────────────────────┘  │
    │                                                   │
    └────┬────────────────────────────────────────┬────┘
         │                                        │
         │                                        │
    ┌────▼───────────────────────┐    ┌──────────▼─────┐
    │   External Services         │    │ PostgreSQL DB  │
    │  ┌───────────────────────┐ │    ├────────────────┤
    │  │ Razorpay API          │ │    │ users          │
    │  │ ├─ Create/manage      │ │    │ orders         │
    │  │ │  disputes           │ │    │ disputes       │
    │  │ ├─ Process refunds    │ │    │ audit_logs     │
    │  │ └─ Payment verify     │ │    └────────────────┘
    │  │                       │ │
    │  │ Google Gemini API     │ │
    │  │ ├─ Vision analysis    │ │
    │  │ ├─ Text generation    │ │
    │  │ └─ Evidence eval      │ │
    │  └───────────────────────┘ │
    │                             │
    │ Mock APIs (for testing)     │
    │ ├─ Shipping tracker        │
    │ ├─ CRM system              │
    │ └─ Delivery confirmation   │
    └─────────────────────────────┘
```

## Data Model

### Core Entities

#### User

```python
class User:
    id: UUID
    email: str (unique)
    api_token: str (unique, bearer auth)
    created_at: datetime
    updated_at: datetime
```

**Purpose**: Identify customer or merchant accounts
**Indexes**: email, api_token
**Constraints**: email must be valid format

#### Order

```python
class Order:
    id: UUID
    user_id: UUID (FK -> User)
    razorpay_order_id: str
    razorpay_payment_id: str
    amount: int (in cents)
    currency: str (default: "INR")
    status: str (pending, paid, failed, refunded)
    description: str (optional)
    created_at: datetime
    updated_at: datetime
```

**Purpose**: Track merchant payment orders
**Indexes**: user_id, razorpay_order_id, status
**Constraints**: amount > 0, unique razorpay_order_id per user

#### Dispute

```python
class Dispute:
    id: UUID
    order_id: UUID (FK -> Order)
    customer_id: UUID (FK -> User)
    reason_code: str (product_not_received, not_as_described, etc.)
    source: str (bank_webhook, customer_claim)
    status: str (pending, evaluating, auto_submit, flag_for_review, 
                 action_failed, manually_contested, resolved)
    deadline: datetime (when merchant must respond)
    claim_details: str (customer's claim description)
    evidence_json: dict {
        image_data: str (base64),
        mime_type: str
    }
    submission_result: dict {
        decision: str,
        confidence: float,
        reasoning: str,
        evidence_analysis: dict,
        agent_analysis: dict
    }
    requires_human_review: bool
    created_at: datetime
    resolved_at: datetime (nullable)
```

**Purpose**: Track chargebacks and refund claims
**Indexes**: order_id, customer_id, status, deadline, source
**Constraints**: deadline must be in future, one active dispute per order

#### AuditLog (Planned)

```python
class AuditLog:
    id: UUID
    dispute_id: UUID (FK -> Dispute)
    action: str (manual_override, auto_decision, escalation)
    actor_id: UUID (FK -> User)
    old_state: dict
    new_state: dict
    reason: str
    created_at: datetime
```

**Purpose**: Track all changes to disputes (for compliance/debugging)

### Entity Relationships

```
User
├─ 1:N → Order (user has many orders)
│        └─ 1:1 → Dispute (order may have dispute)
│
└─ 1:N → Dispute as customer (user files claim)
```

## Component Descriptions

### 1. Frontend (React + Vite)

**Location**: `frontend/src/`

#### Components

**App.jsx**: Main entry point, tab-based routing
- Renders MerchantDashboard or CustomerPortal based on user selection
- Manages authentication state

**MerchantDashboard.jsx**: Dispute management interface
- Lists all disputes with status, AI recommendation, deadline
- Shows evidence images with vision analysis results
- Provides manual override form for disputes
- Features:
  - Real-time polling (6s interval)
  - Status badges (pending, evaluating, auto_submit, etc.)
  - AI confidence score display
  - Manual override with reasoning
- **TODO**: Search, filter, pagination, bulk actions

**CustomerPortal.jsx**: Customer order and claim interface
- Signup → Create order → Razorpay payment → File claim
- Evidence photo upload
- Claim status tracking
- Features:
  - Email-based signup (no password)
  - Order creation with custom amount/currency
  - Razorpay Checkout integration
  - Refund claim form with evidence
- **TODO**: Claim history, appeal, auth recovery

#### API Client

**api.js**: HTTP wrapper around `/base_url/api/`
- Handles authentication headers (Bearer token, X-Merchant-Token)
- Error handling with retry logic
- JSON serialization/deserialization
- **TODO**: Request deduplication, timeout handling, structured logging

### 2. Backend API (FastAPI)

**Location**: `backend/app/`

#### main.py - REST API Routes

**Merchant Routes**:
- `GET /disputes`: List all disputes (with pagination)
- `GET /disputes/{id}`: Get dispute details + AI analysis
- `POST /disputes/{id}/review`: Manual override decision

**Customer Routes**:
- `POST /auth/signup`: Create customer account
- `POST /orders`: Create new payment order
- `GET /orders`: List customer orders
- `POST /orders/{id}/verify-payment`: Verify Razorpay payment
- `POST /disputes/claim`: File refund claim with evidence

**Public Routes**:
- `GET /health`: Health check
- `POST /webhook`: Razorpay webhook receiver

**Authentication**:
- Middleware checks `X-Merchant-Token` header for merchants
- Middleware checks `Authorization: Bearer <token>` for customers
- Webhook signature verification using HMAC-SHA256

#### agent_pipeline.py - AI Decision Engine

**CrewAI Orchestration**:

1. **process_dispute()**: Handle bank-initiated chargebacks
   - Input: Webhook dispute payload
   - Steps:
     1. Store dispute in `pending` status
     2. Call `analyze_evidence()` (vision analysis)
     3. If confidence < threshold → set `requires_human_review = True`
     4. Launch CrewAI crew with Analyst + Strategist agents
   - Agents:
     - **Analyst Agent**: Gathers shipping, delivery, CRM evidence via mock APIs
     - **Strategist Agent**: Decides `auto_submit` or `flag_for_review`
   - Output: Decision JSON stored in `submission_result`

2. **process_refund_claim()**: Handle customer refund requests
   - Input: Customer claim with evidence image
   - Steps:
     1. Store dispute in `evaluating` status
     2. Launch CrewAI with adjudication agents
   - Output: `approve_refund`, `reject_claim`, or `flag_for_review`

**Tool Definitions**:
- `fetch_shipping_proof()`: Mock API call
- `fetch_delivery_confirmation()`: Mock API call
- `fetch_crm_logs()`: Mock API call
- `submit_contest_to_razorpay()`: Real Razorpay API call

#### vision_analysis.py - Evidence Validation

**Purpose**: Pre-analysis safety net before agent pipeline

**Workflow**:
1. Download reference image from mock API
2. Call Gemini Vision API with both images
3. Analyze: authenticity, relevance, anomalies
4. Return confidence score
5. If confidence < `VISION_CONFIDENCE_THRESHOLD` → set `requires_human_review = True`

**Error Handling**:
- Any API error → flag for human review (fail-safe)
- Timeout → escalate (don't block)
- Malformed response → log and escalate

**Concurrency**:
- Thread-safe API key rotation via lock
- **TODO**: Implement caching for identical images

#### razorpay_client.py - Razorpay API Wrapper

**Features**:
- Signature verification (HMAC-SHA256 with timing-safe comparison)
- Retry logic with exponential backoff (tenacity)
- Timeout handling
- Error classification (transient vs permanent)

**Methods**:
- `verify_signature()`: Validate webhook signature
- `fetch_payment(payment_id)`: Get payment details
- `fetch_dispute()`: Get dispute details
- `contest_dispute()`: Submit dispute contest
- `create_refund()`: Issue refund to customer

**Error Handling**:
- Retries: 5xx, 429, network errors (max 3 attempts)
- No retries: 4xx (invalid request)
- Timeout: 15 seconds per call

#### deadline_scheduler.py - Background Job Runner

**Purpose**: Track dispute deadlines and escalate urgent disputes

**Workflow**:
1. Runs every 5 minutes
2. Queries disputes with `deadline < now() + 24 hours`
3. Flags for manual review if approaching deadline
4. Logs escalations

**Status Tracking**:
- Checks disputes in `("pending", "evaluating")` status
- Sets `requires_human_review = True` if deadline near

**TODO**: Implement alerting and distributed locking

#### database.py - Database Connection

**Uses**: SQLAlchemy ORM + PostgreSQL

**Session Management**:
- Dependency injection via `get_db()` in FastAPI routes
- Automatic transaction rollback on error
- Connection pooling

#### models.py - SQLAlchemy ORM Models

**Defines**:
- User, Order, Dispute models
- Relationships and constraints
- Serialization/deserialization helpers

#### auth.py - Authentication Logic

**Bearer Token**: Simple opaque token storage
- No expiry (TODO)
- No password (hackathon scope)
- No MFA

#### security.py - Security Functions

**Signature Verification**:
- `verify_webhook_signature()`: HMAC-SHA256 validation
- Used by webhook endpoint

### 3. External Integrations

#### Razorpay API

**Endpoints Used**:
- `GET /api/v1/payments/{id}`: Fetch payment details
- `GET /api/v1/disputes/{id}`: Get dispute details
- `PATCH /api/v1/disputes/{id}/contest`: Submit contest with evidence
- Webhooks: Dispute created/updated events

**Authentication**: Basic auth with Key ID + Secret

**Retry Strategy**: 3 attempts, exponential backoff

#### Google Gemini API

**Models Used**:
- `gemini-3.6-flash`: Vision + text understanding (default)

**Prompts**:
- Vision prompt for evidence analysis
- Text prompt for agent reasoning

**Rate Limits**: 10-100 requests/minute (depends on tier)

**Error Handling**: Key rotation via `GEMINI_API_KEYS` env var

#### Mock APIs (Testing)

**Available Endpoints**:
- `fetch_shipping_proof(order_id)`: Returns mock shipping data
- `fetch_delivery_confirmation(order_id)`: Returns mock delivery data
- `fetch_crm_logs(customer_id)`: Returns mock CRM logs

**Deterministic**: Same seed produces same response (reproducible tests)

## Dispute Processing Flow

### Bank-Initiated Chargeback (Webhook)

```
┌─ Razorpay Sends Webhook
│  └─ X-Razorpay-Signature verified
│
├─ Verify Request Signature
│  └─ HMAC-SHA256 match
│
├─ Store Dispute
│  ├─ Check for duplicate (by dispute_id)
│  ├─ Create dispute in "pending" status
│  └─ Extract evidence image (if provided)
│
├─ Vision Analysis
│  ├─ Download reference image from mock API
│  ├─ Call Gemini Vision API
│  ├─ Analyze authenticity & relevance
│  └─ If confidence < threshold → set requires_human_review = True
│
├─ Launch CrewAI Agent Pipeline
│  │
│  ├─ Analyst Agent
│  │  ├─ fetch_shipping_proof(order_id)
│  │  ├─ fetch_delivery_confirmation(order_id)
│  │  ├─ fetch_crm_logs(customer_id)
│  │  └─ Summarize findings
│  │
│  └─ Strategist Agent
│     ├─ Review analyst findings
│     ├─ Evaluate reason code + evidence
│     └─ Decide: auto_submit OR flag_for_review
│
├─ Execute Decision
│  ├─ If auto_submit:
│  │  ├─ Call razorpay_client.contest_dispute()
│  │  ├─ Update status to "manually_contested"
│  │  └─ Store submission result
│  │
│  └─ If flag_for_review:
│     ├─ Set requires_human_review = True
│     ├─ Update status to "flag_for_review"
│     └─ Notify merchant dashboard
│
└─ Return 200 OK to Razorpay
```

### Timeline

- **T+0s**: Webhook received
- **T+1s**: Signature verified, dispute stored
- **T+2s**: Vision analysis (0.5-2s typically)
- **T+5s**: CrewAI agents run (2-4s typical)
- **T+10s**: Razorpay response, webhook acknowledged

## Refund Claim Flow

### Customer-Initiated Claim

```
┌─ Customer Portal: Click "File Claim"
│  ├─ Order ID: pre-selected
│  ├─ Reason: dropdown (product_not_received, etc.)
│  ├─ Details: text field
│  └─ Evidence: image upload
│
├─ Frontend Validation
│  ├─ Required fields check
│  ├─ Image size < 5MB (TODO)
│  └─ Send POST /disputes/claim
│
├─ Backend Processing
│  ├─ Verify customer owns order (via token)
│  ├─ Check order status (must be paid)
│  ├─ Check no existing claim (duplicate prevention)
│  ├─ Store dispute in "evaluating" status
│  └─ Encode image as base64
│
├─ Vision Analysis
│  ├─ Analyze evidence image
│  └─ If confidence < threshold → requires_human_review = True
│
├─ Launch CrewAI Adjudication
│  ├─ Review customer + evidence
│  ├─ Check refund policy
│  └─ Decide: approve_refund OR reject_claim OR flag_for_review
│
├─ Execute Decision
│  ├─ If approve_refund:
│  │  ├─ Call razorpay_client.create_refund()
│  │  ├─ Mark order as "refunded"
│  │  ├─ Return "Refund approved and processing"
│  │  └─ Send confirmation email (TODO)
│  │
│  }}─ If reject_claim:
│     ├─ Mark dispute as "rejected"
│     └─ Notify customer via API (TODO)
│
└─ Return Decision to Frontend
   └─ Show result: approval, rejection, or pending review
```

## Technology Stack

### Backend

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Language** | Python 3.11+ | |
| **Framework** | FastAPI | Type-safe, auto-docs, async |
| **ORM** | SQLAlchemy 2.0 | Database abstraction |
| **Database** | PostgreSQL 15+ | Relational data storage |
| **HTTP Client** | httpx | Async HTTP requests |
| **Retry Logic** | tenacity | Exponential backoff |
| **Job Scheduling** | APScheduler | Background task runner |
| **AI/LLM** | CrewAI | Multi-agent orchestration |
| **AI Vision** | Google Gemini API | Evidence image analysis |
| **Config** | PyYAML | reason_codes.yaml parsing |
| **Validation** | Pydantic v2 | Request/response schemas |
| **Testing** | pytest | Unit testing framework |
| **Auth** | Built-in (no framework) | Bearer token + HMAC |

### Frontend

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Language** | JavaScript (ES6+) | |
| **Framework** | React 18 | UI component library |
| **Build Tool** | Vite | Fast dev server + bundle |
| **Payment UI** | Razorpay Checkout | Secure payment form |
| **Styling** | CSS3 | Responsive design |
| **HTTP Client** | Fetch API | Browser native |
| **Testing** | Jest/Vitest | Unit tests (TODO) |

### DevOps

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Containerization** | Docker | Image packaging |
| **Orchestration** | Docker Compose | Local dev + simple prod |
| **Database** | PostgreSQL 15 | |
| **Reverse Proxy** | Nginx (prod) | HTTPS termination |
| **Secrets** | .env file | Local dev vars |

## Security Architecture

### Authentication Flow

**Merchant**:
```
Frontend → Send X-Merchant-Token header
           ↓
           FastAPI middleware validates token
           ↓
           Route handler gets authenticated merchant
           ↓
           Return merchant-specific disputes
```

**Customer**:
```
Frontend → POST /auth/signup → Get bearer token
           ↓
           Store token in localStorage
           ↓
           Send Authorization: Bearer token header
           ↓
           FastAPI middleware validates
           ↓
           Route handler gets authenticated user
           ↓
           Return user-specific orders
```

### Verification Layers

1. **Webhook Signature**: HMAC-SHA256 with `compare_digest()` (timing-safe)
2. **Payment Verification**: Server-side Razorpay API call before accepting refund
3. **Order Ownership**: Check customer_id matches authenticated user
4. **Bearer Token**: Opaque, randomly generated, unique per user

### Data Protection

**Encryption**:
- Database: No encryption at rest (TODO: implement Fernet)
- Transport: Reverse proxy enforces HTTPS in production
- Evidence images: Currently stored as base64 in DB (TODO: encrypt before storage)

**Secrets Management**:
- API keys in `.env` (not in git)
- Razorpay secret rotated periodically
- Gemini key rotation via `GEMINI_API_KEYS` env var

### Vulnerability Mitigations

| Risk | Mitigation |
|------|-----------|
| **Prompt Injection** | Escape claim_details in Gemini prompt (TODO) |
| **Webhook Race** | Atomic duplicate check (TODO) |
| **Double-Refund** | Idempotency key on Razorpay API (TODO) |
| **Token Replay** | Rate limiting + token expiry (TODO) |
| **CSRF** | CORS headers validation (FastAPI built-in) |
| **XSS** | React auto-escapes by default |
| **SQL Injection** | SQLAlchemy parameterized queries |

## Scalability Considerations

### Current Limitations

1. **In-Process Scheduler**: `deadline_scheduler.py` runs only on single instance
   - Race condition if multiple backends run
   - Tasks lost if backend restarts
   - Solution: Use external job queue (Celery + Redis)

2. **No Pagination**: `/disputes` returns all records
   - O(n) query on large dataset
   - Solution: Implement keyset pagination with indexes

3. **No Caching**: Gemini API called for every dispute
   - High latency + API costs
   - Solution: Redis cache for evidence analysis results

4. **Vision Analysis Blocking**: 30-second timeout blocks request
   - Solution: Async analysis queue + webhook callback

5. **No Connection Pooling Config**: Default SQLAlchemy pool size
   - Solution: Tune pool_size, max_overflow, pool_pre_ping

### Scaling Strategies

**Horizontal Scaling** (multiple backend instances):
```
Load Balancer
├─ Backend 1
├─ Backend 2
└─ Backend 3
    ↓
PostgreSQL (shared DB)
```

**Requirements**:
- External job queue (Celery + RabbitMQ/Redis)
- Distributed locking for scheduler
- Redis cache for Gemini results
- Database read replicas

**Expected Capacity**:
- Current: ~100 disputes/day on single instance
- With scaling: ~10,000 disputes/day per DB
- Bottleneck: Gemini API rate limits

### Database Optimization

**Indexes Needed**:
```sql
CREATE INDEX idx_disputes_order_id ON disputes(order_id);
CREATE INDEX idx_disputes_status ON disputes(status);
CREATE INDEX idx_disputes_deadline ON disputes(deadline);
CREATE INDEX idx_disputes_created_at ON disputes(created_at DESC);
CREATE INDEX idx_orders_user_id ON orders(user_id);
```

**Query Optimization**:
- Add LIMIT to list endpoints (default 20, max 100)
- Use cursor-based pagination for large datasets
- Denormalize dispute count per user for dashboard

---

For deployment strategies, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
For roadmap and planned improvements, see [ROADMAP.md](ROADMAP.md).
