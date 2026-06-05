# 生成 protobuf 代码
.PHONY: proto
proto:
	protoc --go_out=. --go_opt=paths=source_relative \
		--go-grpc_out=. --go-grpc_opt=paths=source_relative \
		proto/arena/v1/*.proto
	python -m grpc_tools.protoc \
		--python_out=python --grpc_python_out=python \
		-I proto proto/arena/v1/*.proto

# 编译 Go binary
.PHONY: build
build:
	cd go && go build -o ../bin/arena-server ./cmd/arena-server

# Docker 构建
.PHONY: docker-server
	docker-server:
		docker build -t arena-server:latest -f docker/Dockerfile.server .

.PHONY: docker-agent
	docker-agent:
		docker build -t arena-agent-minimal:latest -f docker/Dockerfile.agent-minimal .

# Python 开发
.PHONY: sdk-install
sdk-install:
	cd python && uv sync

.PHONY: sdk-test
sdk-test:
	cd python/arena-sdk && uv run pytest
	cd python/arena-verl && uv run pytest
	cd python/arena-verify && uv run pytest

# 全量测试
.PHONY: test
test:
	cd go && go test ./...
	$(MAKE) sdk-test

# 本地开发栈
.PHONY: dev
dev:
	@echo "Starting arena server + vLLM mock..."
	go run ./go/cmd/arena-server &
	# vLLM mock would be started here
