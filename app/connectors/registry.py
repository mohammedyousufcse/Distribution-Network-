"""Registry management for available destination connectors."""

from typing import Dict, List, Optional
from app.connectors.assisted import AssistedConnector
from app.connectors.base import BaseConnector
from app.connectors.devto import DevtoConnector
from app.connectors.discourse import DiscourseConnector
from app.connectors.ghost import GhostConnector
from app.connectors.hashnode import HashnodeConnector
from app.connectors.lemmy import LemmyConnector
from app.connectors.mailchimp import MailchimpConnector
from app.connectors.mastodon import MastodonConnector
from app.connectors.mock import MockConnector
from app.connectors.slack import SlackConnector
from app.connectors.webhook import WebhookConnector

# Central registry instance mapping connector keys to their implementations
_REGISTRY: Dict[str, BaseConnector] = {
    "mock": MockConnector(),
    "mastodon": MastodonConnector(),
    "discourse": DiscourseConnector(),
    "lemmy": LemmyConnector(),
    "devto": DevtoConnector(),
    "ghost": GhostConnector(),
    "webhook": WebhookConnector(),
    "assisted": AssistedConnector(),
    "hashnode": HashnodeConnector(),
    "slack": SlackConnector(),
    "mailchimp": MailchimpConnector(),
}


def get_connector(connector_key: str) -> Optional[BaseConnector]:
    """Retrieve connector instance by key (case-insensitive).

    Args:
        connector_key: Unique identifier for the connector (e.g. 'mock', 'mastodon').

    Returns:
        BaseConnector instance if found, None otherwise.
    """
    return _REGISTRY.get(connector_key.strip().lower())


def register_connector(connector_key: str, connector: BaseConnector) -> None:
    """Register or override a connector instance (useful for testing and extensibility)."""
    _REGISTRY[connector_key.strip().lower()] = connector


def get_available_connectors() -> List[str]:
    """Return a list of all registered connector keys."""
    return list(_REGISTRY.keys())
