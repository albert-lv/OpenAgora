# Arena + veRL + SWE-agent + Qwen3.5-0.8B Demo

## 文件结构

```
examples/veRL-SWE-agent/
├── demo.py       # 完整 demo 脚本（mock + real 模式）
├── tools.json    # SWE-agent 工具定义（OpenAI Function Calling 格式）
└── README.md     # 说明文档
```

## 快速开始

### Mock 模式（无需外部依赖）

```bash
python demo.py --mode mock --steps 50
```

### Real 模式（需要完整环境）

1. 启动 Arena Server:
   ```bash
   ./bin/openagora-server --sandbox=docker
   ```

2. 启动 vLLM (Qwen3.5-0.8B):
   ```bash
   vllm serve Qwen/Qwen3.5-0.8B --enable-auto-tool-choice
   ```

3. 运行 demo:
   ```bash
   python demo.py --mode real --arena localhost:9090 --repo /path/to/repo --issue "Fix bug"
   ```

## 依赖

- Python 3.8+
- PyTorch
- openagora-sdk (real 模式)

## 说明

- **Mock 模式**: 纯模拟运行，验证脚本逻辑和接口正确性
- **Real 模式**: 连接真实 Arena Server + vLLM + SWE-agent Docker
