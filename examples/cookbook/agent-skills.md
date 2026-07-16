# Cookbook: Agent Skills

Arena agents can declare the skills they support. The CLI validates skills from
`task.toml` before starting a rollout.

## Declaring skills in task.toml

```toml
[agent]
name = "claude-code"
model = "claude-sonnet-4"
skills = ["file_io", "bash", "mcp"]
```

## Supported skills by adapter

| Agent | Supported skills |
|-------|------------------|
| `arena-minimal` | `file_io`, `bash` |
| `claude-code` | `file_io`, `bash`, `web_search`, `mcp` |
| `codex-cli` | `file_io`, `bash` |
| `openhands` | `file_io`, `bash`, `browser`, `mcp` |

## Validation

If a task requests a skill the agent does not support, the CLI exits with an error:

```bash
$ ./bin/arena run --task examples/tasks/mcp-tools --agent codex-cli
Error: agent codex-cli does not support skills: ['mcp']
```

## Future

- Skill-specific environment setup (e.g. install MCP servers only when `mcp` is requested)
- Skill discovery from agent image metadata
- Skill-based provider selection (e.g. GPU required for `vision`)
