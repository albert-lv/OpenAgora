# Agent 心跳/健康检查机制实现方案

## 1. 概述

为 `nano-symphony` 引入 agent 心跳/健康检查机制，确保系统能及时发现无响应的 agent 并采取处理措施。

## 2. 设计决策

采用**组合式心跳**设计，兼顾可靠性和覆盖度：

### 2.1 进程级心跳（基础层）
- 在 `spawner` 中维护定时器，agent 进程存活期间自动更新数据库 `heartbeat_at`
- 无需 agent 配合，可检测进程崩溃（exit、SIGKILL、OOM）
- 零侵入，向后兼容

### 2.2 MCP Tool 心跳（增强层）
- 新增 `symphony.heartbeat` MCP tool，agent 可主动调用
- 用于检测 agent 进程存活但卡住（死锁、无限循环）的场景
- 进程级心跳和 MCP 心跳更新同一个 `heartbeat_at` 字段

### 2.3 超时检测与处理
- Orchestrator 每 tick 检查 claimed 状态的 run，对比 `heartbeat_at` 与 `heartbeat_timeout_ms`
- 超时后执行可配置的 stale 处理策略：
  - `cancel_then_retry`：发送 SIGTERM 终止进程，然后安排重试（默认）
  - `retry`：直接释放并安排重试
  - `abandon`：标记为 abandoned

## 3. 架构融入

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Orchestrator  │     │    Spawner      │     │     Agent       │
│   (tick loop)   │     │   (heartbeat)   │     │  (MCP tool)     │
├─────────────────┤     ├─────────────────┤     ├─────────────────┤
│ checkStale()    │◄────│ heartbeat_at    │◄────│ symphony.       │
│   ├─ cancel?    │     │   update (DB)   │     │   heartbeat()   │
│   └─ release/   │     │                 │     │                 │
│      retry      │     │ 进程存活时       │     │ 进程卡住时       │
│                 │     │ 自动更新         │     │ 主动更新         │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## 4. 修改清单

1. `src/config.ts` — 新增心跳配置项
2. `src/db/schema.sql` — 新增 `heartbeat_at` 和 `heartbeat_timeout_ms` 字段
3. `src/db/tracker-runs.ts` — 新增心跳更新操作
4. `src/db/tracker-types.ts` — 类型定义更新
5. `src/spawner/index.ts` — 进程级心跳定时器
6. `src/spawner/agent-adapter.ts` — 可选的心跳解析支持
7. `src/mcp/tools.ts` — 新增 `symphony.heartbeat` MCP tool
8. `src/orchestrator/index.ts` — tick 中增加 stale 检测
9. `src/orchestrator/worker.ts` — 处理 stale 后的状态转换
10. 测试文件

## 5. 向后兼容

- 心跳机制是**增量功能**，不破坏现有逻辑
- 旧 run 的 `heartbeat_at` 为 null，`checkStale` 会跳过（视为未启用心跳）
- 不强制 agent 调用 MCP heartbeat，进程级心跳已覆盖大部分场景
- 配置项均有默认值，现有 `.env` 无需改动
