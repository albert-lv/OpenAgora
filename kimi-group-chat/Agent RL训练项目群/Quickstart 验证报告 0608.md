# Quickstart 验证报告（2026-06-08）

## 环境
- macOS, Docker 可用但 mock sandbox 模式已验证
- 仓库：main 分支最新（commit 1f32458）

## 验证结果

### 1. make build ✅
- 编译通过，产出 ./bin/arena-server

### 2. arena-server --sandbox=mock ✅
- 启动成功，监听 :9090，sandbox=mock
- `docker` 和 `mock` 两个 flag 值均工作正常

### 3. make demo ✅
- 编译通过，产出 ./bin/arena-demo
- 注意：arena-demo 内部自带 Docker provider，在无 Docker 环境会失败（预期行为，用于集成测试）

### 4. run.sh ✅（4 秒内完成，远小于 5 分钟目标）
- arena-sdk 安装成功（uv 优先路径生效）
- CreateRollout → WaitForDone → success
- 发现：run.sh 未检测项目 .venv，导致系统 python3 找不到已安装的 arena-sdk
- **已修复**：run.sh 现在优先检测并使用项目 .venv/bin/python（见 patch）

### 5. logprobs 验证 ⚠️
- **代码审查结论**：proxy.go 的 `nonStreamResponse` 和 `streamResponse` 均正确提取并保存 `choice["logprobs"]` 到 trajectory
- **实际验证**：mock_llm.py 不返回 logprobs，因此 trajectory 中 logprobs 为空
- **推断**：若后端 LLM 返回 logprobs，proxy 会正确捕获并存入 trajectory（代码路径已确认）
- **建议**：mock_llm.py 可补充 `logprobs` 字段以增强测试覆盖

## 未合入的修复
- `examples/quickstart/run.sh`：增加 .venv Python 检测（1 处修改）
