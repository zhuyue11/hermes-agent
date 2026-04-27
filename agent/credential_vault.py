"""Credential vault bridge — thin HTTP client for sidecar credential endpoints.

Used by the credential_fill tool to look up and store website credentials
via the doooo-hub sidecar API.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Sidecar base URL — defaults to localhost:8321, overridable via env
_SIDECAR_URL: Optional[str] = None


def _get_sidecar_url() -> str:
    """Resolve sidecar base URL from config or environment."""
    global _SIDECAR_URL
    if _SIDECAR_URL:
        return _SIDECAR_URL

    # Try environment variable first
    env_url = os.getenv("DOOOO_SIDECAR_URL")
    if env_url:
        _SIDECAR_URL = env_url.rstrip("/")
        return _SIDECAR_URL

    # Try reading from hermes config
    try:
        from hermes_cli.config import load_config
        cfg = load_config()
        port = cfg.get("port", 8321)
        _SIDECAR_URL = f"http://127.0.0.1:{port}"
        return _SIDECAR_URL
    except Exception:
        pass

    # Default
    _SIDECAR_URL = "http://127.0.0.1:8321"
    return _SIDECAR_URL


def vault_lookup(url: str) -> Optional[dict]:
    """Look up stored credentials matching a URL.

    Returns dict with keys: found, service, type, auto_approve,
    username, password, token — or None on error.
    """
    import httpx

    base = _get_sidecar_url()
    try:
        resp = httpx.post(
            f"{base}/site-credentials/lookup",
            json={"url": url},
            timeout=5.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.debug("vault_lookup failed for %s: %s", url, exc)
        return None


def vault_store(
    service: str,
    cred_type: str,
    secret_data: dict,
    label: str = "",
    url_patterns: Optional[list] = None,
) -> bool:
    """Store credentials in the sidecar vault.

    Returns True on success.
    """
    import httpx

    base = _get_sidecar_url()
    body = {
        "type": cred_type,
        "label": label or service,
        "url_patterns": url_patterns or [service],
        **secret_data,
    }
    try:
        resp = httpx.put(
            f"{base}/site-credentials/{service}",
            json=body,
            timeout=5.0,
        )
        resp.raise_for_status()
        result = resp.json()
        return result.get("ok", False)
    except Exception as exc:
        logger.debug("vault_store failed for %s: %s", service, exc)
        return False


def vault_set_auto_approve(service: str, auto_approve: bool) -> bool:
    """Toggle auto-approve for a stored credential.

    Returns True on success.
    """
    import httpx

    base = _get_sidecar_url()
    try:
        resp = httpx.patch(
            f"{base}/site-credentials/{service}/auto-approve",
            json={"auto_approve": auto_approve},
            timeout=5.0,
        )
        resp.raise_for_status()
        result = resp.json()
        return result.get("ok", False)
    except Exception as exc:
        logger.debug("vault_set_auto_approve failed for %s: %s", service, exc)
        return False
