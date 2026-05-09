# learning-hub-worker

Background Workers for the Multimodal AI Learning Hub. Handles long-running tasks like document processing, video transcription, and AI task generation.

## Overview

This repository contains Celery workers that process:
- Document text extraction and chunking
- Video/audio transcription
- Embedding generation
- Quiz generation (async)
- Essay grading (async)
- Flashcard generation (async)

## Tech Stack

| Component | Technology |
|-----------|------------|
| Task Queue | Celery |
| Message Broker | Redis |
| Processing | Python libraries (PyPDF2, Whisper, etc.) |
| Storage | MinIO, Qdrant |

## Directory Structure

```
learning-hub-worker/
├── src/
│   ├── tasks/
│   │   ├── document.py       # Document processing
│   │   ├── media.py          # Video/audio processing
│   │   ├── quiz.py           # Quiz generation
│   │   ├── essay.py          # Essay grading
│   │   └── flashcards.py    # Flashcard generation
│   ├── processors/
│   │   ├── text_extractor.py
│   │   ├── chunker.py
│   │   └── embedder.py
│   └── utils/
│       ├── minio_client.py
│       └── qdrant_client.py
├── tests/
├── docs/
├── Dockerfile
├── requirements.txt
└── celery_app.py
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Start Celery worker
celery -A celery_app worker --loglevel=info

# Start Flower (optional - monitoring)
celery -A celery_app flower --port=5555
```

## Environment Variables

```env
# Redis
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/db

# Storage
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_BUCKET=documents-bucket

# Vector DB
QDRANT_HOST=localhost
QDRANT_PORT=6333

# AI Service
AI_SERVICE_URL=http://localhost:8001
AI_SERVICE_API_KEY=your_key
```

## Tasks

### Document Processing

| Task | Description | Queue |
|------|-------------|-------|
| `process_document` | Extract text, chunk, embed PDF/DOCX | `document-processing` |
| `process_video` | Transcribe audio, extract frames | `media-processing` |
| `process_audio` | Transcribe audio files | `media-processing` |

### AI Tasks

| Task | Description | Queue |
|------|-------------|-------|
| `generate_quiz` | Generate quiz questions | `ai-tasks` |
| `generate_flashcards` | Create flashcards | `ai-tasks` |
| `grade_essay` | Grade essay submission | `ai-tasks` |

## Task Example

```python
# Trigger task from API
from src.tasks.document import process_document

# Async task
process_document.delay(document_id="uuid", file_type="pdf")
```

## Monitoring

- **Celery Flower**: http://localhost:5555
- **Redis CLI**: `redis-cli` to monitor queues

## Related Documentation

- [Main Docs](../README.md) - System overview
- [API Contracts](../communication/api-contracts.md) - Service contracts
- [System Design](../3-architecture/system-design.md) - Architecture details