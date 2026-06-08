# Arena + veRL 端到端 Demo (Mock 环境)

这个目录包含一个 **完全自包含** 的端到端 demo，演示 ArenaRolloutProvider 如何在 mock 环境下生成 `token_level_rewards`，并与 veRL 的 DataProto 格式对齐。

## 前置条件

只需要 Python 3.10+ 和 PyTorch（无需 Docker、vLLM、GPU 或真实 Arena server）：

```bash
pip install torch tensordict
```

如果已安装 arena-verl 和 arena-sdk（开发模式）：

```bash
pip install -e python/arena-sdk
pip install -e python/arena-verl
```

> **注意**：veRL 和 transformers 是可选依赖。如果未安装，demo 会自动降级到纯 mock 模式，跳过 veRL DataProto 断言，但仍能验证核心逻辑。

## 快速运行

```bash
cd examples/verl-integration
python demo_train_step.py
```

预期输出（摘要）：

```
======================================================================
Arena + veRL End-to-End Demo (token-level rewards)
======================================================================

Provider created successfully (mock client + mock tokenizer).
Fake prompt batch built: bsz=2, prompt_length=10

Calling generate_sequences() ...
Done.

----------------------------------------------------------------------
Output field inspection
----------------------------------------------------------------------
  prompts                   shape=[2, 10]      dtype=torch.int64
  responses                 shape=[2, 64]      dtype=torch.int64
  response_mask             shape=[2, 64]      dtype=torch.int64
  token_level_rewards       shape=[2, 64]      dtype=torch.float32
  input_ids                 shape=[2, 74]      dtype=torch.int64
  attention_mask            shape=[2, 74]      dtype=torch.int64
  position_ids              shape=[2, 74]      dtype=torch.int64

----------------------------------------------------------------------
Assertion checks
----------------------------------------------------------------------
  [PASS] token_level_rewards exists with shape (2, 64) and dtype float32
  [PASS] sample 0: valid_tokens=6, reward_per_token=0.1667
  [PASS] sample 1: valid_tokens=6, reward_per_token=0.1667

  Episode rewards (sum over response_length): [1.0, 1.0]
  [PASS] Episode reward conserved (sum == 1.0 for each sample)

======================================================================
All assertions passed!
...
======================================================================
```

## 验证要点

1. **`token_level_rewards` 字段存在** — 与 `response_ids` 同形状 `[bsz, response_length]`
2. **dtype 为 float32** — 符合 veRL 对 reward 张量的期望
3. **episode reward 守恒** — 每个样本的 `token_level_rewards.sum()` 等于原始 episode reward（1.0）
4. **与 `response_mask` 对齐** — pad token 的 reward 为 0，有效 token 的 reward 均匀分配

## 文件说明

| 文件 | 说明 |
|------|------|
| `demo_train_step.py` | 主 demo 脚本，包含 MockArenaClient、MockTokenizer、和完整断言 |
| `train.py` | 原始 veRL 集成示例骨架（供参考） |

## 扩展建议

- 将 `MockArenaClient` 替换为真实 `ArenaClient` 即可连接真实 Arena server
- 将 `MockTokenizer` 替换为 `AutoTokenizer.from_pretrained(model_path)` 即可使用真实 LLM tokenizer
- 将 `verify_command` 设置为真实 pytest 命令即可运行带验证的 rollout
