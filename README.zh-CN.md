# OpenAgora

[![Go CI](https://github.com/albert-lv/OpenAgora/actions/workflows/go.yml/badge.svg)](https://github.com/albert-lv/OpenAgora/actions/workflows/go.yml)
[![Python CI](https://github.com/albert-lv/OpenAgora/actions/workflows/python.yml/badge.svg)](https://github.com/albert-lv/OpenAgora/actions/workflows/python.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Go Version](https://img.shields.io/badge/Go-1.25+-00ADD8?logo=go)](https://go.dev/)
[![Python Version](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python)](https://www.python.org/)

[English](README.md) | 简体中文

**Arena 是一个开源的 rollout、验证与轨迹平面，面向智能体强化学习。**

它提供了 RL 训练器（veRL、ROLL、TRL）与智能体执行环境之间缺失的基础设施层。无论你是构建代码智能体、网页智能体还是通用自主系统，Arena 都能为你提供可复现、可观测且支持 RL 的执行管道。

---

## Arena 是什么？

使用强化学习训练智能体，仅仅调用 LLM API 是远远不够的。你还需要：

- **受控的 rollouts** —— 确定性采样、token 预算与轨迹捕获
- **沙箱执行** —— 安全、可复现的智能体运行环境
- **解耦的验证** —— 奖励计算与智能体逻辑相互独立
- **结构化的轨迹数据** —— 供 PPO、GRPO、DPO 等算法使用的训练级数据

Arena 将以上四项能力以可组合、语言无关的平面形式提供。

### 四大平面

| 平面 | 用途 | 状态 |
|-------|---------|--------|
| **Rollout 控制平面** | 带采样注入与轨迹捕获的 LLM 代理 | ✅ 可用 |
| **沙箱平面** | 容器化智能体执行（Docker v1） | ✅ 可用 |
| **验证平面** | 结构化 SWE-bench 验证 + 多语言解析器 | ✅ 可用 |
| **轨迹数据平面** | 结构化、仅追加的轨迹存储 | ✅ 可用 |

详见 [docs/architecture.md](docs/architecture.md) 了解完整设计。

---

## 快速开始

5 分钟内运行你的第一个 rollout。

### 前置要求

- [Docker](https://docs.docker.com/get-docker/)
- [Go 1.25+](https://go.dev/dl/)
- [Python 3.10+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)（用于 Python 开发）

### 1. 克隆并构建

```bash
git clone https://github.com/albert-lv/OpenAgora.git
cd OpenAgora
make build
```

### 2. 启动 Arena 服务

```bash
./bin/openagora-server
# 服务监听 :9090
```

> **注意：** Quickstart 默认使用 Docker 沙箱提供者。请确保 Docker 已安装并正在运行。如果没有 Docker，可以使用 mock 沙箱启动服务：
> ```bash
> ./bin/openagora-server --sandbox=mock
> ```
> mock 提供者不会创建真实容器，但代理、轨迹、验证等流程仍可正常工作。

> **关于 LLM 后端：** 默认的 `task.json` 指向 mock LLM。Arena 支持 Ollama、vLLM 和 SGLang 作为推理后端。代理会为所有后端注入 `logprobs`，并为 vLLM/SGLang 注入 `top_logprobs`。详见 [docs/getting-started.md](docs/getting-started.md) 了解后端配置说明。

### 3. 运行你的第一个 Rollout

在另一个终端中：

```bash
cd examples/quickstart
./run.sh
```

你应该能看到一个 rollout 完成，包含已捕获的轨迹步骤和奖励。

更多详情请查看 [examples/quickstart/README.md](examples/quickstart/README.md) 和 [docs/getting-started.md](docs/getting-started.md)。

---

## 演示：Code Colosseum 仪表盘

要运行一个完整的端到端演示，展示**实时智能体对决**和**真正改进模型的 GRPO 训练循环**，请启动 **Code Colosseum** 技术栈。

关键点：

- 训练器启动一个 **OpenAI 兼容的 LLM 服务**，用于提供当前 actor 策略。
- 每次 Arena rollout 都会调用该服务，因此每次 GRPO 更新都会立即反映在下一代生成中。
- 仪表盘实时显示**随迭代改进的奖励/损失曲线**。

### 一键演示

```bash
docker compose -f examples/code-colosseum/docker-compose.yml up --build
```

然后打开 **http://localhost:3000**。首次运行会将配置的模型（默认 `Qwen/Qwen2.5-0.5B-Instruct`）下载到挂载的 HuggingFace 缓存目录（`~/.cache/huggingface`）。

要使用其他模型，请编辑 `examples/code-colosseum/docker-compose.yml` 中的 `MODEL_NAME`，例如 `Qwen/Qwen3.5-0.8B`。

### 本地开发

分别运行各个服务（适合调试 UI、编排器或训练器时）：

1. **安装 Python 依赖**

   ```bash
   cd examples/code-colosseum/backend
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e ../../../python/openagora-sdk
   pip install fastapi uvicorn pydantic
   ```

   训练器还需要 `torch`、`transformers`、`peft`、`fastapi` 和 `uvicorn`（可在同一或另一个虚拟环境中安装）。

2. **启动 Arena 服务**

   ```bash
   ./bin/openagora-server
   ```

3. **启动 Code Colosseum 编排器**

   ```bash
   cd examples/code-colosseum
   PROBLEMS_DIR=./problems TRAINING_METRICS_PATH=./backend/data/metrics.jsonl \
     uvicorn backend.main:app --host 0.0.0.0 --port 8080
   ```

4. **启动 GRPO 训练器 / 策略 LLM 服务**

   ```bash
   cd examples/code-colosseum/training
   python3 train_colosseum.py
   ```

   训练器在端口 `8000` 启动 LLM 后端，并将指标写入 `METRICS_PATH`。编排器通过 `/api/training/status` 提供这些数据。

5. **启动仪表盘**

   ```bash
   cd examples/code-colosseum/dashboard
   npm install
   npm run dev
   ```

   然后打开 **http://localhost:5173**。

### 仪表盘标签页

- 🌌 **指挥中心** —— 史诗级的 Arena + GRPO 指挥中心：实时对决、智能体代码、战斗日志和 GRPO 奖励分布一屏尽览。
- ⚔️ **竞技场** —— 选择题目，让两个智能体对决，实时观看代码面板和战斗日志中的对决过程。
- 🏆 **排行榜** —— Elo 评分和胜负平记录。
- 📈 **训练** —— 实时 GRPO 奖励/损失/KL 曲线及每组奖励分布。

完整演示指南请查看 [examples/code-colosseum/README.md](examples/code-colosseum/README.md)。

---

## 演示：Relationship Chat RL

一个最小化的端到端 PPO 示例，教会小型语言模型以更共情的方式回复伴侣的消息。它使用：

- **Actor 模型**：`Qwen/Qwen3.5-0.8B`（在 CPU 上使用 LoRA 微调）
- **Rollout 后端**：通过 Ollama 的 `qwen3.5:0.8b`
- **沙箱**：本地（macOS 上无需额外的 Docker-in-Docker）
- **验证**：一个简单的评分器，检查必须包含/避免的短语

### 一键演示

```bash
cd examples/relationship-chat-rl
docker compose up --build
```

该技术栈会启动 Ollama、Arena 服务和 CPU 训练器。首次运行使用从 `~/.cache/huggingface` 挂载的 HuggingFace 缓存，因此请确保 `Qwen/Qwen3.5-0.8B` 已预下载到该目录。

### 你将看到什么

Rollout 和 PPO 更新完成后，打开 Arena 仪表盘 **http://localhost:9091**：

| Rollouts | Verify Stats | Token Stats |
|---|---|---|
| ![Relationship Chat Rollouts](screenshots/relationship-chat-rollouts.png) | ![Relationship Chat Verify Stats](screenshots/relationship-chat-verify-stats.png) | ![Relationship Chat Token Stats](screenshots/relationship-chat-token-stats.png) |

训练器将指标写入 `examples/relationship-chat-rl/data/metrics.jsonl`，并将 LoRA 检查点保存到 `examples/relationship-chat-rl/checkpoints/checkpoint-1/`。

完整指南请查看 [examples/relationship-chat-rl/README.md](examples/relationship-chat-rl/README.md)。

---

## 为什么选择 Arena？

| 能力 | Arena | ROCK | LiteLLM | E2B | SWE-Gym |
|-----------|-------|------|---------|-----|---------|
| 带主动控制的 LLM 代理 | ✅ | ❌ | 被动 | ❌ | ❌ |
| 每次 rollout 的采样注入 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 独立的验证平面 | ✅ | ❌ | ❌ | ❌ | 耦合 |
| RL 级轨迹 schema | ✅ | ❌ | ❌ | ❌ | ❌ |
| 语言无关的智能体契约 | ✅ | 部分 | 不适用 | 部分 | 部分 |

---

## 项目结构

```
OpenAgora/
├── go/                      # Go 核心（服务、代理、沙箱编排）
│   ├── cmd/                 # 二进制文件（openagora-server、demo）
│   └── pkg/                 # 可复用包
├── proto/                   # Protobuf / gRPC schema
├── python/                  # Python 生态
│   ├── openagora-sdk/           # Arena 的 Python 客户端
│   ├── openagora-verify/        # 验证插件
│   └── openagora-verl/          # veRL 训练器适配器
├── docker/                  # Docker 镜像
├── docs/                    # 文档
├── examples/                # Quickstart 和训练器集成
├── Makefile                 # 常用开发任务
└── README.md                # 你在这里
```

---

## 安装

### Go 服务

```bash
make build
# 输出：./bin/openagora-server
```

### Python SDK

```bash
cd python/openagora-sdk
uv sync
```

### Docker 镜像

```bash
make docker-server    # openagora-server:latest
make docker-agent     # openagora-agent-minimal:latest
```

---

## 使用示例

### 构建自定义智能体

任何遵循 [沙箱契约](docs/sandbox-contract.md) 的容器都可以在 Arena 中运行。契约很简单：

1. 从 `/sandbox/.arena/task.json` 读取任务
2. 通过 Arena 注入的 `OPENAI_BASE_URL` 路由 LLM 调用
3. 通过写入 `/sandbox/.arena/done` 发出完成信号

就是这样——语言无关、框架无关。

### Python 客户端

```python
from openagora_sdk.client import ArenaClient

client = ArenaClient("localhost:9090")

rollout_id = client.create_rollout(
    task_id="my-task",
    image="openagora-agent-minimal:latest",
    llm_backend="http://localhost:8000/v1",
)

result = client.wait(rollout_id)
print(f"Status: {result['status']}, Reward: {result['reward']}")
```

更多示例请查看 [examples/](examples/)。

---

## 路线图

我们正在公开构建 Arena。以下是我们接下来的计划：

- [ ] 额外的沙箱提供者（E2B、OpenSandbox）
- [ ] Parquet 和 S3 轨迹后端
- [ ] 面向在线 RL 的流式轨迹消费
- [x] 结构化 SWE-bench 风格验证
- [ ] LLM-as-judge 验证
- [ ] 分布式 rollout 工作器
- [ ] 可观测性仪表盘

有想法？欢迎开启 [讨论](https://github.com/albert-lv/OpenAgora/discussions) 或 [issue](https://github.com/albert-lv/OpenAgora/issues)。

---

## 贡献

我们欢迎贡献！请阅读我们的 [贡献指南](CONTRIBUTING.md) 开始。

几个快速参与的方式：

- **报告 bug** —— [创建 issue](https://github.com/albert-lv/OpenAgora/issues/new?template=bug_report.md)
- **请求功能** —— [创建 issue](https://github.com/albert-lv/OpenAgora/issues/new?template=feature_request.md)
- **提交改进** —— [创建 pull request](https://github.com/albert-lv/OpenAgora/pulls)
- **传播分享** —— 给仓库加星并分享给更多人

请注意，本项目发布了 [贡献者行为准则](CODE_OF_CONDUCT.md)。参与即表示你同意遵守其条款。

---

## 社区

- 💬 [GitHub Discussions](https://github.com/albert-lv/OpenAgora/discussions) —— 提问、分享想法
- 🐛 [GitHub Issues](https://github.com/albert-lv/OpenAgora/issues) —— bug 报告和功能请求
- 📧 安全问题请直接邮件联系维护者，而非公开创建 issue

---

## 许可证

OpenAgora 采用 [Apache License 2.0](LICENSE) 许可证。

---

<p align="center">Built with ❤️ for the open agentic RL community.</p>
