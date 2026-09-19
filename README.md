# CampusConnect

A secure digital platform for managing college club events, proposals, venue booking, budgeting, approvals, resources, and post-event records.

## Project Status

🚧 Under Active Development

Current development stage:
- Project foundation completed
- Authentication foundation completed
- Authentication API completed
- RBAC foundation currently being implemented

CampusConnect is currently under active development. Features are being developed and verified incrementally through automated test suites and containerized environments.

## Current Technology Stack

Backend:
- Python 3.12
- FastAPI
- SQLAlchemy (async)
- PostgreSQL 16
- Alembic

Frontend:
- React
- TypeScript
- Vite

Infrastructure:
- Docker
- Docker Compose

Testing:
- Pytest
- API integration tests

## Current Architecture

CampusConnect follows a modular architecture with FastAPI handling API routing, versioning (/api/v1), and dependency injection. The persistence layer uses PostgreSQL with async SQLAlchemy sessions, and database migrations are managed via Alembic.

## Current Completed Components

The following components are currently implemented and verified with automated test suites:
- PostgreSQL database foundation with async session lifecycle
- Database migrations with Alembic
- Hall booking conflict prevention via PostgreSQL EXCLUDE constraint (tree_gist)
- FastAPI application setup with structured configuration and health checks
- Institutional authentication service (AuthService)
- Argon2id password hashing and verification
- JWT access tokens with strict validation
- Opaque refresh token generation with SHA-256 storage
- Refresh token rotation and reuse detection
- Authentication API endpoints (/register, /login, /refresh, /logout, /me)
- HttpOnly, SameSite-configured cookie handling for refresh tokens
- End-to-end authentication unit and integration tests

## Planned Development

The following features are planned for future development:
- Role-Based Access Control (RBAC) guards and permission matrix
- Club management and governance
- Event proposal workflow (event details, resource requests)
- Hall booking and scheduling interfaces
- Multi-tier budget requests and expense management
- Multi-level sequential approval workflow (Faculty Advisor, Dean, Principal, Finance)
- In-app and email notifications
- Role-specific dashboards and audit logging UI
- Post-event reporting and documentation
- Financial settlement and invoice reconciliation

## Development

### Prerequisites
- Docker and Docker Compose
- Node.js (v20+) and npm (for local frontend development)
- Python (3.12+) (for local backend development)

### Running with Docker Compose

1. Copy environment template:
   `ash
   cp .env.example .env
   `
2. Start containers:
   `ash
   docker compose up -d
   `
3. Run database migrations:
   `ash
   docker compose exec backend alembic upgrade head
   `

### Verification Endpoints

- API Health Check: http://localhost:8000/api/v1/health
- OpenAPI Documentation: http://localhost:8000/docs
- Frontend Development Server: http://localhost:5173

### Running Backend Tests

Run all tests inside the backend container:
`ash
docker compose exec -e ENV=test backend pytest -v
`

## Repository Structure

`
.
├── backend/            # FastAPI backend, models, migrations, tests
├── frontend/           # React + TypeScript frontend application
├── infrastructure/     # Docker configuration files
├── docs/               # System documentation and architecture references
├── docker-compose.yml  # Local multi-container orchestration
└── .env.example        # Environment variable template
`

## Security

Currently implemented security controls:
- Argon2id password hashing with distinct per-user salts
- Short-lived JWT access tokens
- Opaque refresh tokens stored only as SHA-256 hashes
- Automatic invalidation of entire token family upon refresh token reuse detection
- Refresh tokens delivered solely via HttpOnly, SameSite=lax, scoped path cookies
- Generic authentication error messages to prevent account enumeration
- Exclusion constraints at database level to prevent double-booking race conditions

*Note: Security controls are actively being developed and expanded as modules are added.*
