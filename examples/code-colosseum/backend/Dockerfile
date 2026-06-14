# Code Colosseum orchestrator backend.
FROM python:3.12-slim

WORKDIR /app

# Install Python SDK from the repo.
COPY python/openagora-sdk /openagora-sdk
RUN pip install --no-cache-dir /openagora-sdk

COPY examples/code-colosseum/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY examples/code-colosseum/backend /app/backend
COPY examples/code-colosseum/problems /app/problems

ENV PYTHONPATH=/app
ENV PROBLEMS_DIR=/app/problems
ENV ARENA_ENDPOINT=localhost:9090
ENV ARENA_AGENT_IMAGE=openagora-code-colosseum-agent:latest
ENV ARENA_LLM_BACKEND=http://mock-llm:8000/v1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
