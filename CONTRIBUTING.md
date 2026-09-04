# Contributing to Chargeback Responder

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing to the project.

## Code of Conduct

Be respectful, inclusive, and professional. We're building a welcoming community for all contributors.

## How to Contribute

### Reporting Bugs

Found a bug? Please open an issue on GitHub with:

1. **Clear title** describing the bug
2. **Steps to reproduce** the issue
3. **Expected behavior** vs actual behavior
4. **Environment details**:
   - OS (Linux, macOS, Windows)
   - Python version
   - Docker version
   - Browser (if frontend issue)
5. **Error messages** or logs (use code blocks)
6. **Screenshots** if applicable

### Suggesting Features

Have an idea? Open an issue with:

1. **Clear description** of the feature
2. **Use case** and why it's needed
3. **Proposed solution** (if you have one)
4. **Alternatives** you've considered
5. **Impact** on existing functionality

### Submitting Code Changes

#### 1. Fork & Clone
```bash
git clone https://github.com/arya-aashish/RazorPay-Hackathon-.git
cd chargeback-responder
git checkout -b feature/your-feature-name
```

#### 2. Set Up Development Environment

**Backend**:
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
```

**Frontend**:
```bash
cd frontend
npm install
```

#### 3. Make Your Changes

- Create a new branch with a descriptive name
- Follow the coding standards (see below)
- Add tests for new functionality
- Update documentation as needed

#### 4. Test Your Changes

**Backend**:
```bash
cd backend
pytest tests/ -v
# Or specific test
pytest tests/test_agent_pipeline.py -v
```

**Frontend**:
```bash
cd frontend
npm run lint
npm run build
```

#### 5. Commit & Push

```bash
git add .
git commit -m "Fix: brief description of changes"
git push origin feature/your-feature-name
```

Use commit prefixes:
- `feat:` - new feature
- `fix:` - bug fix
- `docs:` - documentation update
- `test:` - add tests
- `refactor:` - code refactoring
- `perf:` - performance improvement
- `chore:` - maintenance

#### 6. Create a Pull Request

Open a PR with:
- **Title**: Clear description
- **Description**: Why this change, what it does
- **Related Issues**: Link to relevant GitHub issues
- **Testing**: How to verify the changes work
- **Screenshots** (if UI changes)

## Coding Standards

### Python (Backend)

**Style Guide**: PEP 8 with some additions

```bash
# Check code style
pylint backend/app/

# Format code
black backend/app/

# Sort imports
isort backend/app/
```

**Requirements**:
- Type hints for functions (use `Optional`, `List`, `Dict`, etc.)
- Docstrings for classes and public methods
- Meaningful variable names
- Maximum line length: 100 characters

Example:
```python
from typing import Optional, List
from models import Dispute

def get_disputes_by_status(status: str) -> List[Dispute]:
    """
    Retrieve all disputes matching the given status.
    
    Args:
        status: The dispute status (pending, resolved, etc.)
        
    Returns:
        List of Dispute objects matching the status
    """
    return db.query(Dispute).filter(Dispute.status == status).all()
```

### JavaScript/React (Frontend)

**Style Guide**: Airbnb React style guide

```bash
# Check code style
npm run lint

# Fix issues
npm run lint -- --fix
```

**Requirements**:
- Use functional components with hooks
- JSDoc comments for complex functions
- Meaningful variable names (avoid `x`, `data`, `temp`)
- Component files: PascalCase (`MyComponent.jsx`)
- Utility files: camelCase (`myUtil.js`)

Example:
```javascript
/**
 * Dispute card component displaying dispute details and AI recommendation
 * @param {Object} dispute - Dispute object
 * @param {Function} onOverride - Callback for manual override action
 */
function DisputeCard({ dispute, onOverride }) {
  return (
    <div className="dispute-card">
      {/* Component JSX */}
    </div>
  );
}
```

### General Requirements

- **Meaningful comments**: Explain *why*, not *what*
- **DRY**: Don't Repeat Yourself—extract common logic
- **SOLID principles**: Single Responsibility, Open/Closed, Liskov, Interface Segregation, Dependency Inversion
- **Error handling**: Don't silently fail; log and handle gracefully
- **No hardcoded values**: Use constants or environment variables

## Testing Requirements

### Backend
- New features must include unit tests
- Minimum 80% code coverage for new code
- Tests in `backend/tests/` directory
- Use pytest with descriptive test names

```python
def test_dispute_status_flag_for_review_when_confidence_low():
    """AI should flag for review if vision confidence below threshold"""
    dispute = create_test_dispute()
    # Test logic
    assert dispute.requires_human_review is True
```

### Frontend
- Components should have corresponding tests
- Test file: `ComponentName.test.jsx`
- Use React Testing Library for UI tests
- Test user interactions, not implementation details

## Documentation

Update documentation when:
- Adding new API endpoints → Update `API.md`
- Changing system architecture → Update `ARCHITECTURE.md`
- Adding new deployment steps → Update `docs/DEPLOYMENT.md`
- Fixing known issues → Update `docs/TROUBLESHOOTING.md`

## Branch Naming

Use descriptive branch names:
- `feature/add-pagination` ✅
- `fix/webhook-race-condition` ✅
- `docs/update-readme` ✅
- `test-123` ❌ (too vague)

## Pull Request Checklist

Before submitting your PR, ensure:

- [ ] Code follows style guidelines
- [ ] Tests pass locally (`pytest` / `npm test`)
- [ ] New tests added for new functionality
- [ ] Documentation updated
- [ ] No unnecessary console.logs or debug code
- [ ] Commit messages are clear and descriptive
- [ ] Branch is up to date with `main`
- [ ] No merge conflicts

## Review Process

1. **Automated checks**: CI/CD runs tests and linting
2. **Code review**: Maintainers review your changes
3. **Feedback**: Address any requested changes
4. **Approval**: Maintainers approve and merge

## Development Workflow

### Local Development

```bash
# Terminal 1: Backend
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Frontend
cd frontend
npm run dev

# Terminal 3: Tests (optional)
cd backend
pytest --watch  # or similar watch mode
```

### Using Docker

```bash
# Build and run with Docker Compose
docker compose up -d --build

# View logs
docker compose logs -f backend
docker compose logs -f postgres

# Run tests in container
docker compose exec backend pytest tests/
```

## Getting Help

- **Questions?** Open a GitHub discussion
- **Need guidance?** Ask on issues before starting heavy work
- **Found a security issue?** Email privately—don't open public issue

## Project Structure

```
chargeback-responder/
├── backend/
│   ├── app/
│   │   ├── agent_pipeline.py    # CrewAI orchestration
│   │   ├── models.py             # Database models
│   │   ├── razorpay_client.py    # Razorpay API wrapper
│   │   ├── vision_analysis.py    # Gemini vision integration
│   │   └── main.py               # FastAPI routes
│   ├── tests/                    # Unit tests
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx               # Main app component
│   │   ├── MerchantDashboard.jsx # Merchant view
│   │   ├── CustomerPortal.jsx    # Customer view
│   │   └── api.js                # API client
│   └── package.json
├── docs/                         # Documentation
├── README.md                     # Project overview
└── docker-compose.yml            # Local development setup
```

## Areas for Contribution

### Good for Beginners
- Documentation improvements
- Bug fixes with clear reproduction steps
- Adding test cases
- UI/UX enhancements (frontend only)

### Intermediate
- Adding new API endpoints
- Improving error handling
- Adding features from the roadmap
- Performance optimizations

### Advanced
- Security improvements
- Architecture refactoring
- Multi-instance scalability
- Integration with external services

## Roadmap

Check [ROADMAP.md](ROADMAP.md) for planned features and priorities. Feel free to tackle items from there!

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing! Your efforts help make Chargeback Responder better for everyone.
