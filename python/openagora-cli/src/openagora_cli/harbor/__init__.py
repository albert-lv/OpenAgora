"""Harbor integration for OpenAgora.

Allows OpenAgora to import and run tasks from the Harbor registry.
Harbor tasks already use the ``task.toml`` + ``instruction.md`` format,
so the integration focuses on discovery, download, and registration.
"""

from openagora_cli.harbor.backend import HarborRegistryBackend
from openagora_cli.harbor.client import HarborClient

__all__ = ["HarborClient", "HarborRegistryBackend"]
