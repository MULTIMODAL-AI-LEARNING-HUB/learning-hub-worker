# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 1.x     | ✅         |

---

## Deploying Securely

Before running in production, **you must** replace all default placeholder values in each service's .env file.

### Generate Strong Secrets

`ash
# SECRET_KEY (JWT signing — min 32 chars)
python -c "import secrets; print(secrets.token_hex(32))"

# INTERNAL_API_KEY (service-to-service auth — min 16 chars)
python -c "import secrets; print(secrets.token_hex(16))"
`

### Required Environment Variables per Service

#### learning-hub-api
| Variable | Requirement |
|---|---|
| SECRET_KEY | Min 32 chars, must be unique and random |
| INTERNAL_API_KEY | Min 16 chars, must match learning-hub-ai and learning-hub-worker |
| DB_PASSWORD | Strong unique password |
| MINIO_ROOT_USER | Change from minioadmin default |
| MINIO_ROOT_PASSWORD | Change from minioadmin123 default |
| GEMINI_API_KEY | Your Google Gemini API key |
| GROQ_API_KEY | Your Groq API key |
| DEBUG | Must be alse in production |

#### learning-hub-ai
| Variable | Requirement |
|---|---|
| INTERNAL_API_KEY | Must match the API service key |
| GEMINI_API_KEY | Your Google Gemini API key |
| GROQ_API_KEY | Your Groq API key |

#### learning-hub-worker
| Variable | Requirement |
|---|---|
| INTERNAL_API_KEY | Must match the API service key |
| MINIO_ACCESS_KEY | Change from minioadmin default |
| MINIO_SECRET_KEY | Change from minioadmin123 default |
| DATABASE_URL | Full connection string with strong credentials |

---

## E2E Test Credentials

The e2e/ directory contains test accounts with default credentials:

`
admin@learninghub.com  / AdminPass123!   (local dev only)
e2e_lecturer@test.com  / TestPass123!    (local dev only)
e2e_student@test.com   / TestPass123!    (local dev only)
`

> ⚠️ **These are test-only credentials for local development.** Do NOT use these in production. In CI/CD, override them via environment variables: E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD, E2E_LECTURER_EMAIL, E2E_LECTURER_PASSWORD, E2E_STUDENT_EMAIL, E2E_STUDENT_PASSWORD.

See [learning-hub-web/.env.e2e.example](./learning-hub-web/.env.e2e.example) for the full list.

---

## Reporting a Vulnerability

If you discover a security vulnerability, please do **not** open a public GitHub issue.

Instead, report it privately by opening a [GitHub Security Advisory](https://github.com/MULTIMODAL-AI-LEARNING-HUB/learning-hub-api/security/advisories/new) or emailing the maintainers directly.

We will acknowledge your report within 48 hours and work with you to resolve the issue.

