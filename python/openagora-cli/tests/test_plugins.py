from unittest.mock import patch

from openagora_cli.plugins.manager import PluginManager


def test_plugin_manager_no_plugins_without_env():
    manager = PluginManager()
    assert manager.enabled_plugins == []


def test_plugin_manager_enables_langsmith_with_env():
    with patch.dict("os.environ", {"LANGSMITH_API_KEY": "test-key"}, clear=False):
        manager = PluginManager()
        assert "langsmith" in manager.enabled_plugins


def test_plugin_manager_enables_wandb_with_env():
    with patch.dict("os.environ", {"WANDB_API_KEY": "test-key"}, clear=False):
        manager = PluginManager()
        assert "wandb" in manager.enabled_plugins
