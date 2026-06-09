# nano-symphony 改进方向分析

> 基于 v0.6.9 版本代码结构、功能现状及近期变更趋势的综合分析。
> 分析日期：2026-06-09

---

## 1. 数据库 Schema 演进与迁移机制

**问题/机会**：当前数据库初始化仅通过 `src/db/schema.sql` 一次性执行 `PRAGMA journal_mode=WAL` 后加载完整 schema。CHANGELOG 明确提到 "Breaking schema redesign requires manual DB wipe"，说明每次 schema 变更都是破坏性的。这在生产环境不可持续。

**为什么重要**：随着 plan-run、issue_results、artifacts 等新表持续增加，用户将无法平滑升级。手动删库意味着数据丢失，严重阻碍版本迭代。

**大致怎么做**：
- 引入增量迁移框架（如 `bun:sqlite` + 自定义版本表 `schema_migrations`）
- 每个版本一个 `.sql` 迁移文件，按顺序执行
- 迁移文件分为 `up` 和 `down`，支持回滚
- 启动时自动检测当前 schema 版本并执行 pending migrations

---

## 2. 测试覆盖率与质量度量

**问题/机会**：38 个测试文件覆盖 48 个源码文件，但项目中没有覆盖率报告（`bun test` 未配置 `--coverage`）。CI 仅在 `workflow_dispatch` 时触发，不是每次 push/PR。

**为什么重要**：无法量化测试质量，难以发现未覆盖的临界路径。CI 手动触发意味着 PR 合并前可能未跑测试（如 PR #101 的 TypeScript 错误就是合并后才发现）。

**大致怎么做**：
- 在 `bunfig.toml` 或 CI 中启用 `--coverage`，设置覆盖率门禁（如 80%）
- 将 CI trigger 改为 `push` + `pull_request`，在 PR 合并前强制跑 lint + test
- 对 worker.ts、orchestrator/index.ts 等核心文件补充分支覆盖测试（如 blocker fingerprint 短接逻辑、timeout 场景）
- 引入前端测试到 CI（当前 `frontend` 目录已有 vitest，但 CI 中跑的是 `npm run test`，需确认是否包含前端测试）

---

## 3. 错误处理与边界条件鲁棒性

**问题/机会**：代码中存在多处 "swallow errors" 或 TODO 注释（如 `routes.ts` 中的 `// TODO: Long-term, request-changes could be implemented as addComment + retrigger`）。`worker.ts` 的 `deriveCompletion` 逻辑复杂且分支众多，容易引入回归。

**为什么重要**： orchestrator 是核心调度器，任何边界条件处理不当都会导致任务悬挂或误判。PR #101 就是典型的 "依赖顺序重构后测试未同步" 问题。

**大致怎么做**：
- 将 `deriveCompletion` 的各分支抽成独立的纯函数策略，每个策略配独立测试
- 引入 `neverthrow` 或类似的 Result 类型，强制每个异步操作处理错误分支
- 对 SQLite 操作（`tracker.claimIssue`、`tracker.releaseIssue`）增加重试和冲突检测，避免并发 tick 时的竞态条件
- 为 `spawner` 中 agent 进程意外崩溃（SIGSEGV、OOM killed）增加专门的处理路径

---

## 4. 持久化与长时间运行稳定性

**问题/机会**：Orchestrator 的 `Semaphore` 和 `timer` 都是内存状态。如果进程 crash，已经 claim 的 issue 会在下次启动时通过 `UPDATE symphony_runs SET last_state = 'released'` 恢复，但正在运行的 agent 进程只能通过 `agent_pid` 列来清理。计划运行（plan-run）虽然支持 JSONL journal 恢复，但 orchestrator 的 tick 状态没有持久化。

**为什么重要**：nano-symphony 设计为长时间运行的守护进程（监听 4123 端口），但服务器重启、OOM、Bun 崩溃都会丢失运行中状态，导致任务重跑或重复调度。

**大致怎么做**：
- 将 `symphony_runs` 的 `last_state` 扩展为更细粒度的状态机（`claiming → preparing → running → completing → released`）
- 对 plan-run 的 JSONL journal 机制推广到普通 issue run：每个 attempt 的日志和中间状态也写入 journal
- 引入 graceful shutdown timeout 配置（当前硬编码 30s），并支持保存 inflight 运行状态到 DB
- 考虑支持外部状态存储（如 Redis）作为可选插件，为多实例部署做准备

---

## 5. 可观测性：从日志到指标

**问题/机会**：当前仅有 Pino 文本日志。没有 Prometheus/metrics 端点，没有分布式 tracing，dashboard 也只能看到实时事件流。

**为什么重要**：随着 plan-run 支持并行子 issue，运行链路变长，仅靠日志排查问题效率低下。需要量化指标：调度延迟、agent 成功率、token 消耗趋势、plan 执行耗时分布。

**大致怎么做**：
- 在 `src/http/server.ts` 增加 `/metrics` 端点，暴露基本 counter（`symphony_issues_claimed_total`、`symphony_agent_runs_duration_seconds`、`symphony_plan_runs_failed_total`）
- 使用 OpenTelemetry 或简单的结构化 event 写入 `symphony_events` 表，支持 dashboard 绘制趋势图
- 在 dashboard 增加 "系统健康" 面板：显示当前运行数、队列深度、token 消耗速率、最近失败率
- 对 MCP tool 调用增加 latency histogram，识别慢工具（如 `symphony.emit_result` 可能涉及大 payload 序列化）

---

## 6. 配置管理与校验

**问题/机会**：配置分散在 `.env` 环境变量、`WORKFLOW.md` 的 YAML front matter、以及 `src/config.ts` 的默认值。`WORKFLOW.md` 的校验通过 Zod schema，但 `.env` 没有校验层，运行时缺失字段会导致隐式 fallback。

**为什么重要**：配置错误是生产事故的主要原因。如 `HOST` 设为 `0.0.0.0` 但 `API_TOKEN` 未设置，symphony 会拒绝启动——这是好的。但其他字段如 `MAX_CONCURRENT_AGENTS` 过大可能导致资源耗尽，没有上限保护。

**大致怎么做**：
- 将 `config.ts` 也改为 Zod schema 校验，在启动时统一校验所有环境变量
- 对敏感配置（如 `API_TOKEN` 长度、`MAX_CONCURRENT_AGENTS` 上限）增加合理性检查
- 支持从配置文件（如 `config.json` 或 `config.yaml`）读取，优于纯环境变量（环境变量在 systemd/docker 中容易泄露到子进程）
- 在 dashboard 增加 "配置查看" 只读面板，方便调试时确认生效配置

---

## 7. 性能优化：SQLite 并发与查询效率

**问题/机会**：`tracker.getCandidates()` 和 `tracker.fetchDueRetries()` 是 orchestrator 每 tick 调用的热点查询。当前 `symphony_runs` 和 `symphony_events` 表索引有限，随着 issue 数量增长，tick 延迟可能增加。

**为什么重要**：`ORCHESTRATOR_TICK_MS` 默认 5 秒，如果查询本身耗时几百毫秒，调度延迟会显著影响吞吐量。当前没有 EXPLAIN ANALYZE 或慢查询日志。

**大致怎么做**：
- 为 `symphony_runs.next_due_ts` 增加索引，加速 `fetchDueRetries` 的 range scan
- 为 `symphony_runs.last_state` + `issue_uuid` 的复合查询增加覆盖索引
- 引入查询执行计划分析：在开发模式下定期输出慢查询日志
- 考虑 SQLite 的 `PRAGMA optimize` 或 `ANALYZE` 自动执行，避免统计信息过时导致全表扫描
- 如果 issue 量达到 10k+，评估是否引入外部数据库（如 PostgreSQL）作为可选后端

---

## 8. 安全加固：速率限制与审计日志

**问题/机会**：`API_TOKEN` 是唯一的认证机制，虽然始终启用，但没有速率限制（rate limiting）。`/api/v1/events/stream` 和 `/api/v1/logs/:issueId/:attempt` 的 SSE 连接有 `MAX_SSE_CONNECTIONS = 50` 的上限，但 HTTP API 本身没有请求频率限制。也没有审计日志记录谁调用了什么 API。

**为什么重要**：恶意用户或脚本可以通过暴力请求导致 DoS。API_TOKEN 一旦泄露，没有额外的防护层。

**大致怎么做**：
- 在 Hono middleware 中增加基于内存（或 SQLite）的速率限制：每个 token/IP 每分钟的请求上限
- 对 `/api/v1/issues` 的创建操作增加审计日志表 `api_audit_log`，记录 caller token hash、endpoint、timestamp
- 支持 token 轮换：生成短期有效的 session token，而非长期不变的 API_TOKEN
- 对 agent 的 MCP 连接也增加 rate limit，防止 agent 无限循环调用 `symphony.report_event` 导致日志膨胀

---

## 9. 前端 Dashboard 功能扩展

**问题/机会**：前端是 Solid/Vite 构建的 SPA，功能包括 issue 列表、详情、事件流、日志查看、workflow 编辑器。但缺少一些关键运维能力：如批量操作、历史趋势、系统级指标。

**为什么重要**：dashboard 是运营者的主要操作界面，随着 plan-run 引入，issue 之间的依赖关系、计划执行树、子 issue 状态都需要可视化。

**大致怎么做**：
- 增加 plan-run 可视化：展示 plan 的执行树（issue 依赖关系、并行 pipeline、phase 进度）
- 增加 issue 批量操作：批量暂停、批量取消、批量重试
- 增加 "token 消耗" 图表：按 issue、按 agent kind、按时间维度的 token 使用趋势
- 支持 dark mode（运维工具夜间使用常见）
- 增加实时通知：当 plan-run 需要审批时，浏览器通知或 sound alert
- 前端国际化：当前只有英文界面，README 有中文但前端没有

---

## 10. 文档与开发者体验

**问题/机会**：README 和 CHANGELOG 非常详细，但内部文档仅有两个文件：`docs/WORKFLOW-INTERNALS.md` 和 `docs/WORKFLOW-reference.md`。对于贡献者而言，理解 orchestrator 的 tick 循环、worker 的生命周期、plan-run 的 sandbox 机制都需要阅读源码。

**为什么重要**：项目正在快速迭代（0.6.x 系列在 5 天内发布了 10 个 patch），新功能如 agent resolution unification、binary injection 等对贡献者门槛较高。

**大致怎么做**：
- 为每个核心模块编写 ARCHITECTURE.md：orchestrator 的状态机、spawner 的 adapter 注册机制、plan-runtime 的 sandbox 安全模型
- 引入 Mermaid 或 ASCII 流程图到文档，展示 "issue 从创建到完成的完整生命周期"
- 在 `CONTRIBUTING.md` 中说明测试策略：如何写 unit test（mock tracker）、如何写 integration test（临时数据库）、如何写 e2e test（真实 agent）
- 为 `skills/` 目录的 SKILL.md 增加版本号，与 symphony 版本对齐，避免 agent 使用旧版 skill 导致行为不匹配

---

## 总结优先级矩阵

| 优先级 | 改进方向 | 影响范围 | 实施难度 | 预期收益 |
|--------|----------|----------|----------|----------|
| 🔴 高 | 数据库迁移机制 | 所有用户 | 中 | 消除升级摩擦，保护数据 |
| 🔴 高 | CI 自动化与覆盖率 | 开发流程 | 低 | 防止回归，提升质量 |
| 🟡 中高 | 可观测性/指标 | 运维 | 中 | 快速定位问题，容量规划 |
| 🟡 中高 | 长时间运行稳定性 | 生产部署 | 中 | 减少任务丢失，提升可靠性 |
| 🟡 中 | 安全加固（rate limit） | API 安全 | 低 | 防御 DoS，提升安全 |
| 🟡 中 | 配置管理校验 | 启动可靠性 | 低 | 减少配置错误事故 |
| 🟢 低 | 前端功能扩展 | 用户体验 | 中 | 提升运维效率 |
| 🟢 低 | 性能优化（索引） | 大规模部署 | 低 | 提升调度吞吐量 |
| 🟢 低 | 文档完善 | 社区贡献 | 低 | 降低贡献门槛 |
| 🟢 低 | 错误处理重构 | 代码质量 | 中 | 减少边界 bug |

---

*本文件由 AI 分析生成，基于 `nano-symphony` 仓库 v0.6.9 版本的代码结构。*
