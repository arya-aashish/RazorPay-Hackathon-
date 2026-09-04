# Installation Guide

Complete step-by-step instructions for setting up Chargeback Responder locally or in production.

## Table of Contents

- [System Requirements](#system-requirements)
- [Local Development Setup](#local-development-setup)
- [Production Deployment](#production-deployment)
- [Environment Variables](#environment-variables)
- [Troubleshooting](#troubleshooting)

## System Requirements

### Minimum Requirements
- **OS**: Linux, macOS, or Windows (with WSL2)
- **RAM**: 4 GB (8 GB recommended)
- **Disk**: 2 GB free space
- **CPU**: 2 cores (4 cores recommended)

### Required Software

#### All Platforms
- Docker & Docker Compose (v2.0+)
  - [Docker Installation Guide](https://docs.docker.com/get-docker/)
  - [Docker Compose Installation](https://docs.docker.com/compose/install/)

#### For Local Development
- Python 3.11 or 3.12
- Node.js 18+ and npm 9+
- Git

**Verify installation**:
```bash
docker --version
docker compose --version
python3 --version
node --version
npm --version
```

## Local Development Setup

### Step 1: Clone Repository

```bash
git clone https://github.com/arya-aashish/RazorPay-Hackathon-.git
cd chargeback-responder
```

### Step 2: Create Environment File

Copy the example and add your API keys:

```bash
cp .env.example .env
```

If no `.env.example` exists, create a `.env` file with:

```env
# Database (PostgreSQL)
DATABASE_URL=postgresql://chargeback_user:chargeback_pass@postgres:5432/chargeback_db

# Razorpay (Get from https://dashboard.razorpay.com/settings/api-keys)
RAZORPAY_KEY_ID=your_test_key_id
RAZORPAY_KEY_SECRET=your_test_key_secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret

# Google Gemini API (Get from https://ai.google.dev/tutorials/setup)
GEMINI_API_KEY=your_gemini_api_key
GEMINI_TEXT_MODEL=gemini-3.6-flash
GEMINI_VISION_MODEL=gemini-3.6-flash

# AI orchestration (CrewAI)
# No additional env vars are required for CrewAI. It uses the Gemini key above.

# Security
MERCHANT_API_TOKEN=your_merchant_token
ENCRYPTION_KEY=your_fernet_encryption_key
```

**Generate secure tokens**:
```bash
# Generate encryption key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Generate merchant token
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Step 2.5: Create a PostgreSQL User (Production / Managed DB Only)

If you are using a separate PostgreSQL database outside Docker, create an application user first.

```bash
psql -h your-db-host -U postgres
```

Then run:
```sql
CREATE USER chargeback_app WITH PASSWORD 'strong_password';
CREATE DATABASE chargeback_app_db OWNER chargeback_app;
GRANT ALL PRIVILEGES ON DATABASE chargeback_app_db TO chargeback_app;
```

For local Docker setup, the database user and database are created automatically when you run `docker compose up`.

### Step 3: Start Services with Docker

```bash
docker compose up -d --build
```

This starts:
- **Backend API**: http://localhost:8000
- **Frontend**: http://localhost:5173
- **PostgreSQL**: localhost:5432
- **pgAdmin** (optional): http://localhost:5050

**Verify health**:
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "ok"}
```

### Step 4: View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend
docker compose logs -f postgres
```

### Step 5: Backend Development (Optional)

If you want to run the backend locally without Docker:

```bash
cd backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements-dev.txt

# Run database migrations (if needed)
python -m alembic upgrade head

# Start development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Step 6: Frontend Development (Optional)

If you want to run the frontend locally without Docker:

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Frontend will be at http://localhost:5173

## Production Deployment

### Option 1: Docker (Recommended)

1. **Launch Linux instance** (Ubuntu 22.04 LTS)

2. **Install Docker**:
```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
```

3. **Configure environment**:
```bash
# Set secure variables
export RAZORPAY_KEY_SECRET=your_production_secret
export GEMINI_API_KEY=your_production_key
export DATABASE_URL=postgresql://user:pass@prod-db-host:5432/db
export MERCHANT_API_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
export ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Save to .env
env | grep -E 'RAZORPAY|GEMINI|DATABASE|MERCHANT|ENCRYPTION' > .env
```

4. **Start services**:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

5. **Set up reverse proxy** (Nginx):
```nginx
upstream backend {
    server backend:8000;
}

upstream frontend {
    server frontend:5173;
}

server {
    listen 80;
    # Add your hostname or deployed domain later when hosting
    
    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    # Add your hostname or deployed domain later when hosting
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    # Frontend
    location / {
        proxy_pass http://frontend;
    }
    
    # Backend API
    location /api/ {
        proxy_pass http://backend/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Option 2: Kubernetes

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for Kubernetes YAML configs and Helm charts.

### Option 3: Cloud Platform

- **Heroku**: Use `Procfile` and buildpacks (see Heroku docs)
- **Google Cloud Run**: Build container and deploy
- **AWS ECS**: Create task definitions and services

## Environment Variables

### Required
```env
# Database connection
DATABASE_URL=postgresql://user:password@host:port/database_name

# Razorpay credentials
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=

# Gemini API
GEMINI_API_KEY=

# Security
MERCHANT_API_TOKEN=
ENCRYPTION_KEY=
```

### Optional
```env
# Gemini models (defaults shown)
GEMINI_TEXT_MODEL=gemini-3.6-flash
GEMINI_VISION_MODEL=gemini-3.6-flash

# Fallback Gemini keys (comma-separated)
GEMINI_API_KEYS=key1,key2,key3

# Individual Gemini keys (for rotation)
GEMINI_API_KEY_1=
GEMINI_API_KEY_2=

# Logging
LOG_LEVEL=INFO

# Vision analysis confidence threshold (0.0-1.0)
VISION_CONFIDENCE_THRESHOLD=0.6

# Deadline check interval (seconds)
DEADLINE_CHECK_INTERVAL=300

# Deadline warning window (seconds)
DEADLINE_WARNING_WINDOW=86400
```

## Troubleshooting

### Docker Issues

**Issue**: `docker compose up` fails with permission error
```bash
# Solution: Add user to docker group
sudo usermod -aG docker $USER
newgrp docker
```

**Issue**: Port already in use
```bash
# Solution: Change port in docker-compose.yml or stop conflicting process
docker ps  # Find what's using the port
docker stop <container-id>

# Or use different port
docker compose up -p 9000:8000 -d
```

**Issue**: Database won't connect
```bash
# Check PostgreSQL logs
docker compose logs postgres

# Verify DATABASE_URL format
# postgresql://username:password@hostname:port/database
```

### Backend Issues

**Issue**: "ModuleNotFoundError: No module named 'app'"
```bash
# Solution: Ensure you're in backend directory
cd backend
python -c "from app.main import app"  # Should work
```

**Issue**: "Connection refused" to database
```bash
# Solutions:
# 1. Ensure DATABASE_URL is correct
# 2. Wait for PostgreSQL to start (can take 10-30 seconds)
# 3. Check if volumes persisted: docker compose down -v && docker compose up -d
```

**Issue**: Gemini API "quota exceeded"
```bash
# Solutions:
# 1. Request quota increase on Google Cloud Console
# 2. Use GEMINI_API_KEYS for key rotation
# 3. Implement exponential backoff in vision_analysis.py
```

### Frontend Issues

**Issue**: "Cannot find module" errors after npm install
```bash
# Solution: Clear cache and reinstall
rm -rf node_modules package-lock.json
npm install
```

**Issue**: "Port 5173 already in use" when running locally
```bash
# Solution: Use different port
npm run dev -- --port 3000
```

**Issue**: API requests failing with CORS errors
```bash
# Solution: Verify VITE_API_BASE in .env
VITE_API_BASE=http://localhost:8000
```

### Database Issues

**Issue**: "Database already exists" during initialization
```bash
# Solution: Drop and recreate
docker compose down -v  # Remove volumes
docker compose up -d
```

**Issue**: Large database size
```bash
# Solution: Clean up old disputes/claims
# Access PostgreSQL container
docker compose exec postgres psql -U chargeback_user -d chargeback_db

# SQL commands
DELETE FROM disputes WHERE created_at < now() - interval '90 days';
VACUUM ANALYZE;
```

### API Issues

**Issue**: Webhook not receiving Razorpay events
```bash
# Solutions:
# 1. Verify RAZORPAY_WEBHOOK_SECRET is correct
# 2. Check firewall/NAT rules allow inbound traffic
# 3. Use ngrok for local testing:
#    ngrok http 8000
#    Add ngrok URL to Razorpay webhook settings
```

**Issue**: "Invalid signature" errors
```bash
# Solution: Verify webhook secret in Razorpay dashboard
# and RAZORPAY_WEBHOOK_SECRET in .env match
```

## Health Checks

### Verify Installation

```bash
# Backend health
curl http://localhost:8000/health

# Database connection
curl http://localhost:8000/disputes  \
  -H "X-Merchant-Token: $MERCHANT_API_TOKEN"

# Frontend
curl http://localhost:5173
```

### Logs

```bash
# View all logs
docker compose logs

# Real-time logs
docker compose logs -f

# Specific service with timestamps
docker compose logs --timestamps backend

# Last 100 lines
docker compose logs --tail 100
```

## Next Steps

1. Read [README.md](README.md) for feature overview
2. Check [API.md](API.md) for API documentation
3. Review [ARCHITECTURE.md](ARCHITECTURE.md) for system design
4. See test examples in `backend/tests/`

## Getting Help

- **Installation issues?** Check [Troubleshooting](#troubleshooting)
- **Not covered here?** Open an issue on GitHub
- **Security questions?** See [CONTRIBUTING.md](CONTRIBUTING.md)
