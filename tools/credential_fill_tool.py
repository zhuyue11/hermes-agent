#!/usr/bin/env python3
"""
Credential Fill Tool — Secure website login credential injection.

When the agent encounters a login form during browser automation, this tool
injects stored credentials directly into the form fields without exposing
the plaintext values to the LLM.

Flow:
  1. Agent calls credential_fill(url, username_ref, password_ref, ...)
  2. Tool checks the sidecar vault for a matching credential
  3a. If found: injects via browser_type() — LLM never sees the values
  3b. If not found: triggers credential_callback to ask the user, stores
      the response for future use, then injects

The tool result returned to the LLM only contains status messages, never
credential values.
"""

import json
import logging
from typing import Callable, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def credential_fill_tool(
    url: str,
    username_ref: Optional[str] = None,
    password_ref: Optional[str] = None,
    submit_ref: Optional[str] = None,
    token_ref: Optional[str] = None,
    task_id: Optional[str] = None,
    credential_callback: Optional[Callable] = None,
    vault_lookup: Optional[Callable] = None,
    vault_store: Optional[Callable] = None,
    vault_set_auto_approve: Optional[Callable] = None,
) -> str:
    """Fill login credentials from the vault or prompt the user.

    Args:
        url: Current page URL (used for credential matching).
        username_ref: Element ref for username/email field (e.g. "@e3").
        password_ref: Element ref for password field (e.g. "@e5").
        submit_ref: Element ref for submit/login button (optional).
        token_ref: Element ref for bearer token input (alternative to user/pass).
        task_id: Browser session task ID for isolation.
        credential_callback: Platform callback(service, cred_type, url) -> dict.
            Blocks until user enters credentials in the UI.
        vault_lookup: Callable(url) -> dict|None. Checks vault for matching cred.
        vault_store: Callable(service, type, secret_data, label, url_patterns).
            Stores newly collected credentials.
        vault_set_auto_approve: Callable(service, bool). Toggles auto-approve.

    Returns:
        JSON string with status (never contains credential values).
    """
    if not url:
        return _error("url is required")

    # --- Step 1: Look up existing credentials ---
    cred_data = None
    service = None
    auto_approve = False

    if vault_lookup:
        try:
            result = vault_lookup(url)
            if result and result.get("found"):
                service = result.get("service")
                auto_approve = result.get("auto_approve", False)
                cred_type = result.get("type")
                if cred_type == "username_password":
                    cred_data = {
                        "type": "username_password",
                        "username": result.get("username"),
                        "password": result.get("password"),
                    }
                elif cred_type == "bearer_token":
                    cred_data = {
                        "type": "bearer_token",
                        "token": result.get("token"),
                    }
        except Exception as exc:
            logger.warning("Vault lookup failed for %s: %s", url, exc)

    # --- Step 1b: If found but not auto-approved, ask for approval ---
    if cred_data is not None and not auto_approve:
        if credential_callback is None:
            # No way to ask — proceed anyway (tool is useless if we block)
            pass
        else:
            approval = credential_callback(service, "__approve__", url)
            if not approval or approval.get("denied"):
                return json.dumps({
                    "filled": False,
                    "service": service,
                    "reason": "User denied credential use.",
                }, ensure_ascii=False)
            # If user chose "always allow", persist the preference
            if approval.get("always") and vault_set_auto_approve:
                try:
                    vault_set_auto_approve(service, True)
                except Exception:
                    pass

    # --- Step 2: If no stored credential, ask the user ---
    if cred_data is None:
        if credential_callback is None:
            return _error(
                "No stored credentials found for this site and credential "
                "prompt is not available. Ask the user manually via clarify."
            )

        # Determine credential type from provided refs
        if token_ref and not (username_ref or password_ref):
            cred_type = "bearer_token"
        else:
            cred_type = "username_password"

        # Extract a clean service name from the URL
        try:
            parsed = urlparse(url)
            service = parsed.hostname or url
            # Strip www. prefix
            if service.startswith("www."):
                service = service[4:]
        except Exception:
            service = url

        try:
            user_response = credential_callback(service, cred_type, url)
        except Exception as exc:
            return _error(f"Failed to get credentials from user: {exc}")

        if not user_response:
            return json.dumps({
                "filled": False,
                "reason": "User skipped credential entry.",
            }, ensure_ascii=False)

        # Parse the response
        if cred_type == "username_password":
            username = user_response.get("username", "")
            password = user_response.get("password", "")
            if not username or not password:
                return _error("Username and password are both required.")
            cred_data = {
                "type": "username_password",
                "username": username,
                "password": password,
            }
        elif cred_type == "bearer_token":
            token = user_response.get("token", "")
            if not token:
                return _error("Token is required.")
            cred_data = {"type": "bearer_token", "token": token}

        # Store for future use
        if vault_store and cred_data:
            try:
                secret = (
                    {"username": cred_data["username"], "password": cred_data["password"]}
                    if cred_data["type"] == "username_password"
                    else {"token": cred_data["token"]}
                )
                vault_store(
                    service=service,
                    cred_type=cred_data["type"],
                    secret_data=secret,
                    label=service,
                    url_patterns=[service],
                )
            except Exception as exc:
                logger.warning("Failed to store credential for %s: %s", service, exc)

    # --- Step 3: Inject into the browser form ---
    if cred_data is None:
        return _error("No credentials available to fill.")

    return _inject_credentials(
        cred_data=cred_data,
        service=service or "unknown",
        username_ref=username_ref,
        password_ref=password_ref,
        submit_ref=submit_ref,
        token_ref=token_ref,
        task_id=task_id,
    )


def _inject_credentials(
    cred_data: dict,
    service: str,
    username_ref: Optional[str],
    password_ref: Optional[str],
    submit_ref: Optional[str],
    token_ref: Optional[str],
    task_id: Optional[str],
) -> str:
    """Inject credentials into browser form fields via browser_type."""
    from tools.browser_tool import browser_type, browser_click

    filled_fields = []
    errors = []

    if cred_data["type"] == "username_password":
        if username_ref:
            result = json.loads(browser_type(username_ref, cred_data["username"], task_id))
            if result.get("success"):
                filled_fields.append("username")
            else:
                errors.append(f"username: {result.get('error', 'unknown')}")

        if password_ref:
            result = json.loads(browser_type(password_ref, cred_data["password"], task_id))
            if result.get("success"):
                filled_fields.append("password")
            else:
                errors.append(f"password: {result.get('error', 'unknown')}")

    elif cred_data["type"] == "bearer_token":
        ref = token_ref or username_ref
        if ref:
            result = json.loads(browser_type(ref, cred_data["token"], task_id))
            if result.get("success"):
                filled_fields.append("token")
            else:
                errors.append(f"token: {result.get('error', 'unknown')}")

    # Optionally click the submit button
    if submit_ref and filled_fields:
        try:
            result = json.loads(browser_click(submit_ref, task_id))
            if result.get("success"):
                filled_fields.append("submit")
        except Exception:
            pass  # Non-critical — agent can click submit itself

    # Register injected values for redaction in future snapshots
    _register_for_redaction(cred_data)

    if errors:
        return json.dumps({
            "filled": len(filled_fields) > 0,
            "service": service,
            "type": cred_data["type"],
            "filled_fields": filled_fields,
            "errors": errors,
        }, ensure_ascii=False)

    return json.dumps({
        "filled": True,
        "service": service,
        "type": cred_data["type"],
        "filled_fields": filled_fields,
    }, ensure_ascii=False)


def _register_for_redaction(cred_data: dict) -> None:
    """Register credential values for session-scoped redaction.

    Ensures that if credential values somehow appear in subsequent
    browser_snapshot output, they are masked before reaching the LLM.
    """
    try:
        from agent.redact import add_session_secrets
        secrets = []
        if cred_data.get("username"):
            secrets.append(cred_data["username"])
        if cred_data.get("password"):
            secrets.append(cred_data["password"])
        if cred_data.get("token"):
            secrets.append(cred_data["token"])
        if secrets:
            add_session_secrets(secrets)
    except ImportError:
        # add_session_secrets not yet implemented — will be added in Phase 2d
        pass
    except Exception as exc:
        logger.debug("Failed to register credentials for redaction: %s", exc)


def check_credential_fill_requirements() -> bool:
    """Credential fill requires browser tools to be available."""
    try:
        from tools.browser_tool import browser_type
        return True
    except ImportError:
        return False


# =============================================================================
# OpenAI Function-Calling Schema
# =============================================================================

CREDENTIAL_FILL_SCHEMA = {
    "name": "credential_fill",
    "description": (
        "Fill login credentials for a website from the stored credential vault. "
        "Use this when you encounter a login form during web browsing.\n\n"
        "If stored credentials exist for the site, they are injected directly "
        "into the form fields — you will NOT see the actual values.\n"
        "If no stored credentials exist, the user will be prompted via a secure "
        "form to enter them. The credentials are then stored for future use.\n\n"
        "Provide the element refs from the page snapshot for the form fields "
        "you want filled (username, password, and optionally the submit button)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": (
                    "The current page URL. Used to match against stored "
                    "credentials by domain."
                ),
            },
            "username_ref": {
                "type": "string",
                "description": (
                    "Element ref for the username or email input field "
                    "(e.g. '@e3'). Omit for bearer token auth."
                ),
            },
            "password_ref": {
                "type": "string",
                "description": (
                    "Element ref for the password input field "
                    "(e.g. '@e5'). Omit for bearer token auth."
                ),
            },
            "submit_ref": {
                "type": "string",
                "description": (
                    "Element ref for the login/submit button (e.g. '@e7'). "
                    "Optional — if provided, the button is clicked after "
                    "credentials are filled."
                ),
            },
            "token_ref": {
                "type": "string",
                "description": (
                    "Element ref for a bearer token input field. Use this "
                    "instead of username_ref/password_ref for token-based auth."
                ),
            },
        },
        "required": ["url"],
    },
}


# --- Helpers ---
def _error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


# --- Registry ---
from tools.registry import registry

registry.register(
    name="credential_fill",
    toolset="credential_fill",
    schema=CREDENTIAL_FILL_SCHEMA,
    handler=lambda args, **kw: credential_fill_tool(
        url=args.get("url", ""),
        username_ref=args.get("username_ref"),
        password_ref=args.get("password_ref"),
        submit_ref=args.get("submit_ref"),
        token_ref=args.get("token_ref"),
        task_id=kw.get("task_id"),
        credential_callback=kw.get("credential_callback"),
        vault_lookup=kw.get("vault_lookup"),
        vault_store=kw.get("vault_store"),
    ),
    check_fn=check_credential_fill_requirements,
    emoji="🔐",
)
