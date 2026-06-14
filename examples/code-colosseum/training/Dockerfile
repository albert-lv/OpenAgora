# Code Colosseum trainer image.
# Extends the existing CPU trainer image used by verl-integration.
FROM openagora-cpu-trainer:latest

WORKDIR /app

# Copy training code and problem bank.
COPY examples/code-colosseum/training/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY examples/code-colosseum/training /app/training
COPY examples/code-colosseum/backend/problems.py /app/backend/problems.py
COPY examples/code-colosseum/problems /app/problems

ENV PROBLEMS_DIR=/app/problems
ENV PYTHONPATH=/app
ENV METRICS_PATH=/app/data/metrics.jsonl
ENV CHECKPOINT_DIR=/app/checkpoints

CMD ["python3", "-u", "/app/training/train_colosseum.py"]
