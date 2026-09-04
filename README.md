# Chargeback Responder

An intelligent, AI-powered chargeback and refund dispute management system built with FastAPI, React, CrewAI, and Razorpay integration. Automates dispute analysis, evidence collection, and response strategy to minimize chargeback losses.

## Features

### Intelligent Dispute Analysis
- **Automated Decision Engine**: AI agents analyze disputes using CrewAI to evaluate evidence and suggest responses
- **Visual Evidence AI**: Gemini Vision API analyzes merchant-provided evidence images for authenticity and relevance
- **Multi-Agent Analysis**: Specialist agents (Analyst + Strategist) collaborate to build robust defense strategies
- **Human Review Escalation**: Complex disputes automatically escalated to merchant review queue

### Razorpay Integration
- **Webhook Receiver**: Real-time dispute notifications from Razorpay
- **Auto-Contest Submission**: Automatically submits disputes with strong evidence
- **Payment Verification**: Full merchant-initiated refund flow with signature verification
- **Refund Management**: Process customer refund claims with approval workflow

### Dual Portal System

**Merchant Dashboard**
- View all incoming disputes with AI-generated recommendations
- Visual evidence analysis results
- Manual override capability with reasoning
- Track dispute status and outcomes
- Filter by status and reason code

**Customer Portal**
- Self-service refund claim submission
- Evidence image upload
- Real-time claim status tracking
- Order history

### Deadline Management
- Automatic escalation of disputes approaching deadline
- Background scheduler tracks payment deadlines
- Flags disputes requiring urgent human attention

## Tech Stack

### Backend
- **Framework**: FastAPI (async web framework)
- **Database**: PostgreSQL with SQLAlchemy ORM
- **AI/LLM**: 
  - CrewAI for multi-agent orchestration
  - Google Gemini API for vision analysis and text generation
- **Background Jobs**: APScheduler for deadline tracking
- **HTTP Client**: httpx with tenacity for resilient API calls
- **Authentication**: Bearer token-based auth for merchants and customers

### Frontend
- **Framework**: React 18 with Vite
- **Payment Checkout**: Razorpay Checkout integration
- **Styling**: CSS3 with responsive design
- **Build Tool**: Vite (fast development server + optimized builds)

### Deployment
- **Containerization**: Docker + Docker Compose
- **Database**: PostgreSQL 15+
- **Environment**: Linux

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+ (for local development)
- Node.js 18+ (for frontend development)
- Razorpay Account (test/prod keys)
- Google Gemini API Key

### Environment Setup

1. **Clone the repository**:
```bash
git clone https://github.com/arya-aashish/RazorPay-Hackathon-.git
cd chargeback-responder
```

2. **Configure environment variables** (`.env`):
```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/chargeback_db

# Razorpay
RAZORPAY_KEY_ID=your_key_id
RAZORPAY_KEY_SECRET=your_key_secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret

# Google Gemini AI
GEMINI_API_KEY=your_gemini_api_key
GEMINI_TEXT_MODEL=gemini-3.6-flash
GEMINI_VISION_MODEL=gemini-3.6-flash

# Security
MERCHANT_API_TOKEN=your_secure_merchant_token
ENCRYPTION_KEY=your_fernet_encryption_key  # Generate: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

3. **Start services**:
```bash
docker compose up -d --build
```

This starts:
- Backend API: `http://localhost:8000`
- Frontend: `http://localhost:5173`
- PostgreSQL: `localhost:5432`

4. **Verify Health**:
```bash
curl http://localhost:8000/health
```

## API Endpoints

### Merchant APIs
- `GET /disputes` - List all disputes
- `GET /disputes/{id}` - Get dispute details with AI analysis
- `POST /disputes/{id}/review` - Manual override with reasoning
- `POST /webhook` - Razorpay webhook receiver

### Customer APIs
- `POST /auth/signup` - Create customer account
- `POST /orders` - Create payment order
- `POST /orders/{id}/verify-payment` - Confirm payment (Razorpay callback)
- `GET /orders` - List customer orders
- `POST /disputes/claim` - File refund claim with evidence

### Public
- `GET /health` - Health check

## Usage Example

### Merchant Workflow
1. Navigate to Merchant Dashboard
2. View incoming chargebacks from Razorpay
3. Review AI-generated analysis and recommendation
4. Auto-submit with AI decision OR manually override
5. Track dispute status until resolution

### Customer Workflow
1. Navigate to Customer Portal
2. Sign up with email
3. Create order and complete payment with Razorpay Checkout
4. File refund claim if needed
5. Upload evidence (photo/screenshot)
6. Track claim status

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (React SPA)                     │
│         Merchant Dashboard │ Customer Portal                 │
└────────────────┬────────────────────────────────┬────────────┘
                 │                                │
         ┌───────▼────────┐            ┌──────────▼──────┐
         │  FastAPI       │            │  Razorpay API   │
         │  Backend       ◄───────────►│  (webhooks)     │
         └───────┬────────┘            └─────────────────┘
                 │
        ┌────────┼────────┐
        │        │        │
   ┌────▼──┐ ┌───▼──┐ ┌──▼────────┐
   │CrewAI │ │Gemini│ │PostgreSQL │
   │Agents │ │Vision│ │  Database │
   └───────┘ └──────┘ └───────────┘
```

## Dispute Flow

### Bank-Initiated Chargeback
```
Razorpay Webhook
    ↓
Store Dispute (pending)
    ↓
Vision Analysis (safety net)
    ↓
CrewAI Agent Pipeline
  ├─ Analyst Agent: Gather evidence
  ├─ Strategist Agent: Decide strategy
    ↓
Result: auto_submit | flag_for_review
    ↓
If auto_submit: Submit to Razorpay
If flag_for_review: Notify merchant
```

### Customer Refund Claim
```
Customer Portal Claim
    ↓
Upload Evidence Image
    ↓
CrewAI Adjudication
  ├─ Evaluate evidence
  ├─ Check refund policy
    ↓
Result: approve_refund | reject_claim | flag_for_review
    ↓
If approve_refund: Issue via Razorpay
Notify customer of decision
```

## Development

### Backend
```bash
cd backend

# Install dependencies
pip install -r requirements-dev.txt

# Run tests
pytest

# Run locally (with auto-reload)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd frontend

# Install dependencies
npm install

# Development server
npm run dev

# Build for production
npm run build
```

## Testing

### Backend Tests
```bash
cd backend

# Run unit tests
pytest tests/

# Run specific test
pytest tests/test_agent_pipeline.py -v

# With coverage
pytest --cov=app tests/
```

### Integration Tests
```bash
# Requires running backend container
pytest test_claim_flow.py
```

## Configuration

### Reason Codes
Edit `backend/app/reason_codes.yaml` to customize:
- Required evidence types per reason code
- Escalation rules
- Evidence templates

### Vision Analysis Thresholds
In `backend/app/vision_analysis.py`:
- Confidence threshold: `CONFIDENCE_THRESHOLD = 0.6` (adjust for aggression)
- Model selection: `GEMINI_VISION_MODEL` env var

### Deadline Scheduler
In `backend/app/deadline_scheduler.py`:
- Check interval: `300` seconds (5 minutes)
- Warning window: `86400` seconds (24 hours)

## Known Limitations & TODOs

### Security (Pre-Production)
- [ ] Implement token expiry (currently tokens never expire)
- [ ] Add rate limiting (no request throttling)
- [ ] Encrypt sensitive data in database (evidence images currently stored as plain base64)
- [ ] Multi-user merchant accounts (currently all merchants share single token)
- [ ] Implement prompt injection protection for vision analysis

### Scalability
- [ ] Add database indexes for dispute queries
- [ ] Implement pagination on dispute list (currently returns all)
- [ ] Distributed deadline scheduler (currently in-process only)
- [ ] Cache layer for repeated evidence analysis
- [ ] Request deduplication for webhook replay protection

### Features
- [ ] Dispute search/filter (by ID, customer, reason code, date range)
- [ ] Bulk dispute export (CSV/PDF)
- [ ] Analytics dashboard (win rates, dispute trends)
- [ ] Audit trail for manual overrides
- [ ] Merchant webhooks (notify external systems)
- [ ] Customer claim appeals
- [ ] Multi-language support

### Operations
- [ ] Structured logging (currently console-only)
- [ ] Error tracking (Sentry integration)
- [ ] Metrics/monitoring (Prometheus)
- [ ] Automated backups
- [ ] Admin console

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Add tests for new functionality
5. Commit with clear messages
6. Push and create a Pull Request

## License

This project is licensed under the MIT License - see LICENSE file for details.

## Support

For issues, feature requests, or questions:
- Open an issue on GitHub
- Check existing documentation in `backend/tests/README.md`

## Acknowledgments

- Built with [CrewAI](https://github.com/joaomdmoura/crewAI) for multi-agent orchestration
- Vision analysis powered by [Google Gemini API](https://ai.google.dev/)
- Payment integration with [Razorpay](https://razorpay.com/)

---

**Status**: Beta - Use with caution in production. See TODOs above for critical items before full release.
