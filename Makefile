# 生成 protobuf 代码
.PHONY: proto
proto:
	cd go && protoc --go_out=. --go_opt=paths=source_relative \
		--go-grpc_out=. --go-grpc_opt=paths=source_relative \
		-I ../proto ../proto/openagora/v1/*.proto
	mkdir -p go/proto/openagora/v1
	mv go/openagora/v1/*.pb.go go/proto/openagora/v1/ || true
	rm -rf go/openagora
	python3 -m grpc_tools.protoc \
		--python_out=python/openagora-sdk/src --grpc_python_out=python/openagora-sdk/src \
		-I proto proto/openagora/v1/*.proto

# 编译 Go binary
.PHONY: build
build:
	cd go && go build -o ../bin/openagora-server ./cmd/openagora-server

# 编译 Demo binary（内置 Docker provider + mock LLM，用于快速验证）
.PHONY: demo
demo:
	cd go && go build -o ../bin/openagora-demo ./cmd/demo

# Docker 构建
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

# Python 开发
.PHONY: sdk-install
sdk-install:
	cd python/openagora-sdk && uv sync --extra dev
	cd python/openagora-verl && uv sync --extra dev
	cd python/openagora-verify && uv sync --extra dev

.PHONY: sdk-test
sdk-test:
	cd python/openagora-sdk && uv run pytest
	cd python/openagora-verl && uv run pytest
	cd python/openagora-verify && uv run pytest

# 全量测试
.PHONY: test
test:
	cd go && go test ./...
	$(MAKE) sdk-test

# 本地开发栈
.PHONY: dev
dev:
	@echo "Starting OpenAgora server + mock LLM..."
	go run ./go/cmd/openagora-server &
	python3 examples/quickstart/mock_llm.py &
	@echo "OpenAgora server on :9090, mock LLM on :8000"

# 启动 mock LLM（用于 quickstart 无外部 vLLM 时）
.PHONY: mock-llm
mock-llm:
	python3 examples/quickstart/mock_llm.py
