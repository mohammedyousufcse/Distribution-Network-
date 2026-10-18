"""
Destination Catalogue Service.

Loads, validates, and manages configuration-driven destination profiles from destinations.yaml.
Enables 'one connector, many destinations' architecture.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse
import yaml

from app.models.policy import DestinationPolicy


def normalize_url(url: Optional[str]) -> Optional[str]:
    """Normalize URL by stripping trailing slashes and lowercasing scheme/netloc."""
    if not url:
        return None
    url = url.strip()
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url.rstrip("/")
    normalized_netloc = parsed.netloc.lower()
    normalized_path = parsed.path.rstrip("/")
    return urlunparse((
        parsed.scheme.lower(),
        normalized_netloc,
        normalized_path,
        parsed.params,
        parsed.query,
        parsed.fragment,
    ))


class CatalogueService:
    """Manages configuration-driven destination catalogue."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path:
            self.config_path = Path(config_path)
        else:
            # Look in current working directory or project root
            default_path = Path("destinations.yaml")
            if default_path.exists():
                self.config_path = default_path
            else:
                self.config_path = Path(__file__).resolve().parent.parent.parent / "destinations.yaml"

        self._destinations: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        """Load and parse destinations from YAML file."""
        if not self.config_path.exists():
            self._destinations = {}
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        items = data.get("destinations", [])
        self._destinations = {}
        for item in items:
            dest_id = item.get("id")
            if dest_id:
                # Normalize URLs
                if "base_url" in item:
                    item["base_url"] = normalize_url(item["base_url"])
                if "instance_url" in item:
                    item["instance_url"] = normalize_url(item["instance_url"])
                if "webhook_url" in item:
                    item["webhook_url"] = normalize_url(item["webhook_url"])

                self._destinations[dest_id] = item

    def get_destination(self, destination_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve destination configuration by destination ID."""
        return self._destinations.get(destination_id)

    def list_destinations(self, connector_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all destinations, optionally filtered by connector key."""
        if connector_key:
            key = connector_key.strip().lower()
            return [d for d in self._destinations.values() if d.get("connector_key", "").lower() == key]
        return list(self._destinations.values())

    def get_policy(self, destination_id: str) -> Optional[DestinationPolicy]:
        """Convert destination posting_rules into DestinationPolicy."""
        dest = self.get_destination(destination_id)
        if not dest:
            return None

        rules = dest.get("posting_rules", {})
        return DestinationPolicy(
            destination_key=destination_id,
            max_requests_per_window=rules.get("max_posts_per_window", 10),
            window_seconds=rules.get("window_seconds", 3600),
            weekly_frequency_cap=rules.get("weekly_frequency_cap", 70),
            allow_self_promotion=rules.get("allow_self_promotion", True),
            allow_links=rules.get("allow_links", True),
            require_ai_disclosure=rules.get("require_ai_disclosure", False),
            min_text_length=rules.get("min_text_length", 1),
            max_text_length=dest.get("format_limits", {}).get("max_body_length")
            or dest.get("format_limits", {}).get("max_text_length")
            or 50000,
        )

    def resolve_connection(self, destination_id: str) -> Dict[str, Any]:
        """
        Safely resolve connection credentials for destination from environment variables.
        Never exposes raw secrets in static files.
        """
        dest = self.get_destination(destination_id)
        if not dest:
            return {}

        conn: Dict[str, Any] = {}
        for k, v in dest.items():
            if isinstance(v, str) and v.startswith("env:"):
                env_var = v[4:]
                conn[k] = os.environ.get(env_var, "")
            elif k in ("auth_ref", "auth_user_ref"):
                if isinstance(v, str) and v.startswith("env:"):
                    env_var = v[4:]
                    conn_key = "api_key" if "API_KEY" in env_var or "TOKEN" in env_var or "SECRET" in env_var else "username"
                    conn[conn_key] = os.environ.get(env_var, "")

        # Default fallback values for standard keys
        if "auth_ref" in dest and isinstance(dest["auth_ref"], str) and dest["auth_ref"].startswith("env:"):
            token_val = os.environ.get(dest["auth_ref"][4:], "")
            conn["token"] = token_val
            conn["api_key"] = token_val
            conn["webhook_secret"] = token_val

        return conn


# Singleton instance
catalogue_service = CatalogueService()
