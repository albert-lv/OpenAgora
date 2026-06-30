# Relationship-chat agent image.
# Extends the Arena minimal agent with the openai client and our chat/scoring scripts.

FROM openagora-agent-minimal:latest

WORKDIR /app

# Install pip so we can install the openai client.
RUN apk add --no-cache py3-pip
RUN pip3 install --no-cache-dir --break-system-packages openai

COPY examples/relationship-chat-rl/agent/chat_agent.py /app/agent.py
COPY examples/relationship-chat-rl/verify/score_response.py /app/score_response.py

ENTRYPOINT ["python3", "/app/agent.py"]
