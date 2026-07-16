from openagora_cli.registry.backends.github import GitHubBackend
from openagora_cli.registry.backends.local import LocalBackend
from openagora_cli.registry.backends.url import URLBackend

__all__ = ["RegistryBackend", "LocalBackend", "URLBackend", "GitHubBackend"]
