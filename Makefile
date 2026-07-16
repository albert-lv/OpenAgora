# Generate protobuf code
.PHONY: proto
proto:
	cd go && protoc --go_out=. --go_opt=paths=source_relative \
		--go-grpc_out=. --go-grpc_opt=paths=source_relative \
		-I ../proto ../proto/openagora/v1/*.proto
	mkdir -p go/proto/openagora/v1
	mv go/openagora/v1/*.pb.go go/proto/openagora/v1/ || true
	rm -rf go/openagora
	python/openagora-sdk/.venv/bin/python -m grpc_tools.protoc \
		--python_out=python/openagora-sdk/src --grpc_python_out=python/openagora-sdk/src \
		-I proto proto/openagora/v1/*.proto

# Build Go binary
.PHONY: build
build:
	cd go && go build -o ../bin/openagora-server ./cmd/openagora-server

# Build Arena CLI (Python)
.PHONY: build-cli
build-cli:
	cd python/openagora-cli && (uv venv .venv 2>/dev/null || true) && uv pip install -e . --reinstall-package openagora-sdk --python .venv/bin/python
	@echo "arena CLI installed at python/openagora-cli/.venv/bin/arena"

# Build Demo binary (built-in Docker provider + mock LLM for quick validation)
.PHONY: demo
demo:
	cd go && go build -o ../bin/openagora-demo ./cmd/demo

# Docker builds
.PHONY: docker-server
docker-server:
	docker build -t openagora-server:latest -f docker/Dockerfile.server .

.PHONY: docker-agent
docker-agent:
	docker build -t openagora-agent-minimal:latest -f docker/Dockerfile.agent-minimal .

.PHONY: docker-swe-agent
docker-swe-agent:
	docker build -t openagora-swe-agent:latest -f docker/Dockerfile.swe-agent .

.PHONY: docker-cpu-trainer
docker-cpu-trainer:
	docker build -t openagora-cpu-trainer:latest -f docker/Dockerfile.cpu-trainer .

.PHONY: docker-code-colosseum-agent
docker-code-colosseum-agent:
	docker build -t openagora-code-colosseum-agent:latest -f examples/code-colosseum/agent/Dockerfile.agent .

# Code Colosseum demo
.PHONY: colosseum-up
colosseum-up:
	docker compose -f examples/code-colosseum/docker-compose.yml up --build

.PHONY: colosseum-down
colosseum-down:
	docker compose -f examples/code-colosseum/docker-compose.yml down -v

# Python development
.PHONY: sdk-install
sdk-install:
	cd python/openagora-sdk && uv sync --extra dev
	cd python/openagora-verl && uv sync --extra dev
	cd python/openagora-verify && uv sync --extra dev

.PHONY: sdk-test
sdk-test:
	cd python/openagora-sdk && .venv/bin/python -m pytest
	cd python/openagora-verl && .venv/bin/python -m pytest
	cd python/openagora-verify && .venv/bin/python -m pytest

.PHONY: cli-test
cli-test:
	cd python/openagora-cli && .venv/bin/python -m pytest tests/

# Install git hooks for local lint/format checks
.PHONY: install-hooks
install-hooks:
	.venv/bin/pre-commit install

# Full tests
.PHONY: test
test:
	cd go && go test ./...
	$(MAKE) sdk-test
	$(MAKE) cli-test

# Local dev stack
.PHONY: dev
dev:
	@echo "Starting OpenAgora server + mock LLM..."
	go run ./go/cmd/openagora-server &
	python3 examples/quickstart/mock_llm.py &
	@echo "OpenAgora server on :9090, mock LLM on :8000"

# Start mock LLM (used by quickstart when no external vLLM)
.PHONY: mock-llm
mock-llm:
	python3 examples/quickstart/mock_llm.py
