from openagora_cli.agents.registry import default_registry
from openagora_cli.task.config import TaskConfig


def test_registry_lists_builtin_agents():
    registry = default_registry()
    names = registry.list()
    assert "arena-minimal" in names
    assert "claude-code" in names
    assert "codex-cli" in names
    assert "openhands" in names


def test_claude_code_agent_entrypoint():
    registry = default_registry()
    agent = registry.get("claude-code")
    config = TaskConfig()
    task_json, env = agent.prepare_task(config, "write hello world")
    cmd = agent.entrypoint(config, task_json, "write hello world", env)
    assert cmd[0] == "claude"
    assert "write hello world" in cmd


def test_codex_cli_agent_entrypoint():
    registry = default_registry()
    agent = registry.get("codex-cli")
    config = TaskConfig()
    task_json, env = agent.prepare_task(config, "write hello world")
    cmd = agent.entrypoint(config, task_json, "write hello world", env)
    assert cmd[0] == "codex"
    assert "-p" in cmd


def test_skill_validation():
    registry = default_registry()
    agent = registry.get("claude-code")
    assert agent.validate_skills(["mcp"]) == []
    assert agent.validate_skills(["unsupported"]) == ["unsupported"]


def test_arena_minimal_supported_skills():
    registry = default_registry()
    agent = registry.get("arena-minimal")
    assert "file_io" in agent.supported_skills
