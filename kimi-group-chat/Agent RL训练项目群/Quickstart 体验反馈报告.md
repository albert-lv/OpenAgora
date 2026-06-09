# Agent Arena Quickstart 体验反馈报告

## 测试环境

- OS: macOS (Darwin 25.5.0, x64)
- Go: 1.26.1 ✅
- Docker: 28.3.2 ✅
- Python: 3.13.2 ✅
- uv: 0.11.8 ✅

## 测试流程与结果

### 1. Clone + Build ✅

```bash
git clone https://github.com/albert-lv/agent-arena.git
cd agent-arena
make build
```

- 结果：构建成功，产出 `./bin/arena-server`
- 耗时：约 3 秒

### 2. 启动 Server ⚠️ 部分可用

```bash
./bin/arena-server
```

- 服务在 `:9090` 正常监听
- **但日志警告：`sandbox provider not configured; CreateRollout will fail`**
- 这是一个关键问题：README 和 quickstart 都没有提到需要配置 sandbox provider

### 3. 构建 Docker Agent Image ✅

```bash
make docker-agent
```

- 成功构建 `arena-agent-minimal:latest`
- 基于 `python:3.12-slim`，镜像小巧

### 4. 运行 Quickstart ❌ 失败

#### 问题 A：`run.sh` 使用 `pip` 命令不存在

`run.sh` 第 13 行：`pip install -e ...`

在 macOS 和许多 Linux 发行版上，`pip` 命令已不存在，只有 `pip3`。且系统 Python 受 PEP 668 保护（externally-managed），直接 pip install 会报错。

#### 问题 B：Server 缺少 Sandbox Provider 配置

即使修复 pip 问题，执行后 gRPC 返回：

```
StatusCode.UNKNOWN: sandbox provider not configured
```

`go/cmd/arena-server/main.go` 中 `server.New(logger, nil)` 传入 `nil` 配置，导致 sandbox provider 为空。`CreateRollout` 会直接拒绝。

#### 问题 C：Task 默认需要本地 vLLM（localhost:8000）

`task.json` 中 `llm_backend` 指向 `http://localhost:8000/v1`，但 quickstart 并没有指导用户如何启动一个 LLM 后端。README 只是说 "If you do not have a real backend, the minimal agent will still demonstrate the contract"，但实际运行时会因为 sandbox 起不来而无法验证这一点。

### 5. 验证 Demo 二进制文件 ✅ 可用

```bash
cd go && go build -o ../bin/arena-demo ./cmd/demo
./bin/arena-demo
```

- Demo 正确配置了 `docker.NewProvider()` + `ProxyAdvertiseHost: "host.docker.internal"`
- 内置 mock LLM 后端，无需外部 vLLM
- Rollout 成功完成，trajectory 4 steps，proxy 拦截正常
- **说明核心代码是好的，问题出在 quickstart 的入口二进制和文档上**

## 修复建议

### 高优先级

1. **修复 `arena-server` 默认配置**：`go/cmd/arena-server/main.go` 应默认注入 `docker.NewProvider()`，否则 quickstart 的第一步就失败。或者至少提供命令行 flag 启用 Docker provider。

2. **修复 `run.sh` 的 pip 调用**：改为 `pip3` 或 `python3 -m pip`，同时考虑用 `uv` 或 venv 兼容 PEP 668 环境。

3. **补充文档**：在 quickstart 的 Step 2 之后增加一步 "Configure Sandbox Provider" 或说明 `arena-server` 需要额外配置。

### 中优先级

4. **提供 mock LLM 选项**：quickstart 应该有一个不依赖外部 vLLM 的默认路径（像 demo 那样内置 mock），或者提供一个 `make dev` 启动 mock LLM 的方案。目前 `make dev` 里的 vLLM mock 是注释掉的占位符。

5. **统一 Python 依赖路径**：项目用 `uv` 管理，但 `run.sh` 用 `pip install -e`，两者不一致。建议 `run.sh` 调用 `uv run` 或直接让用户用 `uv pip install -e` 进入 venv。

### 低优先级

6. **Makefile 增加 demo 构建目标**：`make demo` 可以构建 `arena-demo`，方便用户快速验证系统是否工作。

7. **Quickstart 预期输出样例**：README 中列出的预期输出（"Status: success, Reward: 1.0"）与实际 demo 输出（Reward: 0.00）不一致，因为 minimal agent 没有实际实现任务逻辑。应调整预期或提供更完整的 quickstart agent。

## 总结

| 步骤 | README 描述 | 实际体验 | 评级 |
|------|------------|---------|------|
| 前置条件 | 列出 Docker/Go/Python/uv | 全部满足 | ✅ |
| 构建 | `make build` | 成功 | ✅ |
| 启动 Server | `./bin/arena-server` | 能启动但无法创建 rollout | ⚠️ |
| 构建 Agent | `make docker-agent` | 成功 | ✅ |
| 运行 Quickstart | `./run.sh` | 完全失败（2 处阻塞） | ❌ |
| 端到端验证 | 预期 success + reward | 仅 demo 二进制可走通 | ⚠️ |

**当前 quickstart 无法在干净环境按 README 走通。** 修复 `arena-server` 的默认 sandbox provider 配置 + `run.sh` 的 pip 兼容性后，可以变成真正的 "5 分钟上手"。
