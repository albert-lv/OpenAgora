# Cookbook: MCP Tools

Model Context Protocol (MCP) tools let an agent call external services during a rollout.

## Concept

In OpenAgora, MCP servers run alongside the agent in the sandbox. The agent adapter
can expose MCP tools by setting the appropriate environment variables and config
files before starting the agent.

## Example task layout

```text
examples/tasks/mcp-tools/
├── task.toml
├── instruction.md
├── environment/
│   └── mcp_config.json
└── tests/
    └── test_tool_use.py
```

## task.toml

```toml
[environment]
image = "openagora-agent-minimal:latest"
env_vars = { MCP_CONFIG_PATH = "/sandbox/.arena/mcp_config.json" }

[agent]
name = "claude-code"
model = "claude-sonnet-4"

[verifier]
command = "python -m pytest tests/"
framework = "pytest"
```

## MCP config

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/sandbox/data"]
    }
  }
}
```

## Future work

- Built-in MCP server adapters in `openagora-cli/agents/installed/`
- Per-task `mcp_servers` section in `task.toml`
- Trajectory logging of MCP tool calls as ATIF observations
