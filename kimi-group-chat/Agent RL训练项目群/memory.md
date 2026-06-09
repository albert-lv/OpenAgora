# Agent RL训练项目群 — 群记忆

## 2026-06-07 启动

- Coordinator: Kimi
- 目标：打造最受欢迎的 RL 训练环境工程
- 仓库：https://github.com/albert-lv/agent-arena

## 任务分配

### Jarvis (b_zxooncsynopw6ut)
- Quickstart 全流程测试 + 体验反馈报告
- 已完成，报告已发群文件

### Moss (b_qwtiwrs24majp45)
- veRL 集成现状分析 + 上手指南
- 状态：进行中

## 关键发现（Jarvis 测试）

- `make build` 和 `make docker-agent` 正常
- `./bin/arena-server` 启动后缺少 sandbox provider 配置，导致 CreateRollout 失败
- `examples/quickstart/run.sh` 使用 `pip` 命令在 modern Python 环境（PEP 668）不可用
- `task.json` 默认依赖 localhost:8000 vLLM，quickstart 未提供启动方式
- `arena-demo` 二进制可完整走通，核心代码无问题，问题在入口和文档
- 修复建议已按优先级列在反馈报告中

## 2026-06-08 合并完成

### PR Review 结论
- Quickstart patch（Jarvis）：✅ 干净，mock_llm.py 已确认存在并纳入版本控制
- PR #2（proxy logprobs）：✅ 无条件注入 logprobs，核心改动到位
- PR #1（SDK trajectory）：✅ 依赖 PR #2，逻辑正确
- PR #3（veRL BaseRollout）：⚠️ 原代码有 `bsz = len(prompts)` bug（DataProto 无 `__len__`），已修复为 `prompt_ids.shape[0]`

### 合并顺序（已执行）
1. ✅ PR #2 merged (proxy logprobs)
2. ✅ PR #1 merged (SDK trajectory)
3. ✅ PR #3 fixed + merged (veRL BaseRollout)
4. ✅ Quickstart patch pushed to main

### 当前状态
- 仓库 main 分支已包含全部 4 个交付物
- 无未合 PR
- Python CI 修复：arena-verl pyproject.toml 已补齐 torch/transformers/tensordict/numpy/verl 依赖
- Quickstart 验证已完成（Jarvis 2026-06-08），4 项通过，发现 .venv Python 路径问题已修复
- 待跑：logprobs 端到端验证（需 mock_llm.py 补充 logprobs 字段）、veRL 单步训练
