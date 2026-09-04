# Roadmap 2026-2027

Strategic priorities and planned features for Chargeback Responder.

## Strategy

Chargeback Responder aims to become the AI-first dispute management platform for fintech and e-commerce merchants. Our roadmap balances:

1. **Security & Compliance** (Q1 2026)
2. **Scalability & Performance** (Q2 2026)  
3. **Merchant Features** (Q3 2026)
4. **Analytics & Reporting** (Q4 2026)

---

## Q1 2026: Security Hardening

### Critical Fixes (Do First)

- [ ] **Encryption at Rest**
  - Implement Fernet encryption for evidence images in database
  - Encrypt sensitive fields: `claim_details`, `submission_result`
  - Add encryption key rotation strategy
  - Estimated effort: 2 days
  - Impact: High (compliance, GDPR)

- [ ] **Token Security**
  - Implement token expiry (30-day default, configurable)
  - Add token revocation capability
  - Implement rate limiting (100 req/min per user, 1000 req/min global)
  - Estimated effort: 3 days
  - Impact: High (security)

- [ ] **Webhook Idempotency**
  - Add idempotency-key header support to Razorpay requests
  - Fix race condition on webhook duplicate processing
  - Atomic dispute creation check
  - Estimated effort: 1 day
  - Impact: High (data integrity)

- [ ] **Prompt Injection Protection**
  - Escape `claim_details` and `reason_code` in Gemini prompts
  - Sanitize all user inputs before LLM calls
  - Add input validation layer
  - Estimated effort: 2 days
  - Impact: Medium (security)

### Secondary Fixes

- [ ] **Merchant Token Multi-User**
  - Support multiple users per merchant account
  - Implement role-based access (admin, analyst, reviewer)
  - Estimated effort: 3 days
  - Impact: Medium

- [ ] **HTTPS Enforcement**
  - Add HSTS headers in FastAPI
  - Document HTTPS requirement in deployment guide
  - Estimated effort: 1 day
  - Impact: Medium

- [ ] **Structured Logging**
  - Implement JSON logging with correlation IDs
  - Add request/response logging (sanitized)
  - Log all sensitive operations with timestamps
  - Estimated effort: 2 days
  - Impact: High (debugging, compliance)

---

## Q2 2026: Scalability & Performance

### Database Optimization

- [ ] **Add Database Indexes**
  ```sql
  CREATE INDEX idx_disputes_order_id ON disputes(order_id);
  CREATE INDEX idx_disputes_status ON disputes(status);
  CREATE INDEX idx_disputes_deadline ON disputes(deadline);
  CREATE INDEX idx_disputes_created_at ON disputes(created_at DESC);
  CREATE INDEX idx_orders_user_id ON orders(user_id);
  ```
  - Estimated effort: 1 day
  - Impact: High (query performance)

- [ ] **Implement Pagination**
  - Add cursor-based pagination to `/disputes` endpoint
  - Support keyset pagination for large datasets
  - Add `skip`, `limit` parameters with limits (max 100)
  - Estimated effort: 2 days
  - Impact: High (UX, performance)

- [ ] **Audit Log Table**
  - Create `audit_logs` table for all dispute changes
  - Log timestamps, actor, action, before/after state
  - Add filtering by date range, action, user
  - Estimated effort: 2 days
  - Impact: Medium (compliance, debugging)

### Caching & Performance

- [ ] **Redis Cache Layer**
  - Cache Gemini vision analysis results (24-hour TTL)
  - Cache dispute list queries
  - Implement cache invalidation strategy
  - Estimated effort: 3 days
  - Impact: High (API cost reduction, latency)

- [ ] **Async Evidence Analysis**
  - Move vision analysis to background queue
  - Webhook returns immediately with `pending_analysis` status
  - Callback updates dispute when analysis completes
  - Estimated effort: 4 days
  - Impact: High (throughput)

- [ ] **Distributed Job Queue**
  - Replace APScheduler with Celery + Redis
  - Support multiple backend instances
  - Implement job status tracking
  - Estimated effort: 5 days
  - Impact: High (reliability, scalability)

### Load Testing

- [ ] **Benchmarking Suite**
  - Load test with 100+ disputes/minute
  - Measure API latency under load
  - Identify bottlenecks
  - Document performance targets
  - Estimated effort: 2 days
  - Impact: Medium (capacity planning)

---

## Q3 2026: Merchant Features

### Dashboard Enhancements

- [ ] **Advanced Search & Filter**
  - Search by dispute ID, order ID, customer name, email
  - Filter by status, reason code, date range, requires_human_review
  - Save search filters as presets
  - Estimated effort: 3 days
  - Impact: High (UX)

- [ ] **Sorting & Export**
  - Sort by all columns (deadline, status, amount, created_at)
  - Export as CSV/PDF
  - Scheduled email exports
  - Estimated effort: 2 days
  - Impact: Medium

- [ ] **Bulk Actions**
  - Select multiple disputes and batch override
  - Bulk download evidence
  - Bulk export for legal review
  - Estimated effort: 2 days
  - Impact: Medium

- [ ] **Dispute Detail Page Improvements**
  - Display full evidence image (not truncated)
  - Show agent analysis step-by-step
  - Display timeline of all changes (audit trail)
  - Estimated effort: 2 days
  - Impact: Medium

- [ ] **Analytics Dashboard**
  - Disputes by status (pie chart)
  - Win rate by reason code
  - Average time to decision
  - Chargeback trends (line chart)
  - ROI calculation (disputes won vs time spent)
  - Estimated effort: 3 days
  - Impact: High (business insights)

### Team Management

- [ ] **User Roles & Permissions**
  - Admin: Full access
  - Analyst: View and override disputes
  - Reviewer: View only
  - Estimated effort: 2 days
  - Impact: Medium

- [ ] **Dispute Assignment**
  - Assign disputes to team members
  - Assignment workflow (analyst → reviewer → decision)
  - Queue management dashboard
  - Estimated effort: 3 days
  - Impact: Medium

- [ ] **Merchant Notifications**
  - Email on new dispute
  - Email on deadline approaching (24h warning)
  - Email when decision made
  - Configurable notification preferences
  - Estimated effort: 2 days
  - Impact: High (UX)

### Customer Portal Improvements

- [ ] **Claim History & Recovery**
  - View past claims without token
  - Access via claim ID + email
  - Claim status notifications
  - Estimated effort: 2 days
  - Impact: Medium

- [ ] **Evidence Preview**
  - Show image preview before submitting
  - Allow image cropping/rotation
  - Estimated effort: 1 day
  - Impact: Low (UX polish)

- [ ] **Appeal Process**
  - Allow customer to appeal rejected claims
  - Re-submit with additional evidence
  - Estimated effort: 2 days
  - Impact: Medium

---

## Q4 2026: Analytics & Monitoring

### Monitoring & Observability

- [ ] **Error Tracking Integration**
  - Integrate Sentry for exception tracking
  - Automatic error alerts to team Slack
  - Error rate dashboards
  - Estimated effort: 1 day
  - Impact: High (incident response)

- [ ] **Metrics & Dashboards**
  - Prometheus metrics export
  - Datadog/New Relic integration
  - SLA tracking (decision time, dispute %,  win rate)
  - Estimated effort: 2 days
  - Impact: High (operations)

- [ ] **Health Checks & Alerts**
  - Database connection health
  - Razorpay API availability
  - Gemini quota usage alerts
  - Slack notifications on failures
  - Estimated effort: 2 days
  - Impact: High (reliability)

### Reporting & Insights

- [ ] **Automated Reports**
  - Daily digest: disputes, decisions, trends
  - Weekly performance report
  - Monthly financial impact
  - Estimated effort: 2 days
  - Impact: Medium

- [ ] **Custom Reports**
  - Merchant-configurable report templates
  - Schedule automated delivery
  - Export as PDF/Excel
  - Estimated effort: 3 days
  - Impact: Medium

- [ ] **Compliance Reports**
  - GDPR data export (user data)
  - Audit trail export
  - Payment records for accounting
  - Estimated effort: 2 days
  - Impact: Medium (compliance)

### Testing & Quality

- [ ] **E2E Testing**
  - Playwright/Cypress test suite
  - Test payment flow end-to-end
  - Test dispute workflow
  - Estimated effort: 4 days
  - Impact: High (reliability)

- [ ] **Security Testing**
  - Penetration testing
  - SQL injection tests
  - XSS/CSRF attack attempts
  - Rate limit testing
  - Estimated effort: 3 days
  - Impact: High (security)

- [ ] **Frontend Test Coverage**
  - Jest/Vitest unit tests
  - React Testing Library for components
  - Target 80%+ coverage
  - Estimated effort: 3 days
  - Impact: Medium

---

## Future Enhancements (2027+)

### ML/AI Improvements

- [ ] **Custom Model Training**
  - Train decision model on merchant's historical data
  - Personalized win-rate predictions
  - Adaptive threshold adjustment per merchant
  - Estimated effort: 10 days
  - Impact: High (performance)

- [ ] **Fraud Detection**
  - Detect potential fraud claims
  - Flag suspicious patterns (duplicate claims, etc.)
  - Estimated effort: 5 days
  - Impact: Medium

### Integrations

- [ ] **Stripe Integration**
  - Support Stripe disputes
  - Same dispute workflow
  - Estimated effort: 3 days
  - Impact: Medium (TAM expansion)

- [ ] **Webhook Delivery**
  - Send webhook events to merchant's server
  - Dispute created, decision made, resolved
  - Retry with exponential backoff
  - Estimated effort: 2 days
  - Impact: Medium

- [ ] **Slack Integration**
  - Post dispute notifications to Slack
  - Interactive dispute approval from Slack
  - Estimated effort: 1 day
  - Impact: Low (convenience)

### Mobile

- [ ] **Mobile App (React Native)**
  - iOS/Android native app
  - Merchant dashboard on mobile
  - Push notifications
  - Estimated effort: 10 days
  - Impact: Low (niche use case)

---

## Dependency Graph

```
Q1: Security
  ↓
Q2: Scalability (depends on Q1)
  ↓
Q3: Features (depends on Q2)
  ↓
Q4: Monitoring (depends on Q1-Q3)
```

**Critical Path**:
1. Encryption at rest (GDPR compliance)
2. Rate limiting (security)
3. Database indexes (performance)
4. Pagination (UX)
5. Dashboard search (merchant request)

---

## Success Metrics

| Metric | Target | Timeline |
|--------|--------|----------|
| **Availability** | 99.5% uptime | Q2 2026 |
| **Latency** | <500ms p95 | Q2 2026 |
| **Decision Time** | <30s average | Q2 2026 |
| **Test Coverage** | >80% | Q4 2026 |
| **Support Response** | <2h SLA | Q3 2026 |

---

## Budget & Resource Allocation

**Estimated Team**:
- 2 Full-stack engineers
- 1 DevOps engineer (part-time)
- 1 Product manager

**Estimated Effort**: ~600 dev-days across 4 quarters

**Priority**: Follow order listed above. Can deprioritize analytics features if security/scalability blocked.

---

## Feedback & Adjustments

This roadmap is living document. Adjust based on:
- Customer feedback (monthly)
- Performance metrics (weekly)
- Security advisories (as needed)
- Market changes (quarterly)

---

Last updated: September 5, 2026
Next review: October 1, 2026
