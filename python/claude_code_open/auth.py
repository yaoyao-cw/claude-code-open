"""Authentication initialization for the Python Claude Code surface."""
from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import pathlib
import platform
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional
from urllib import request as urlrequest

from .errors import AuthError


@dataclass
class AuthConfig:
    type: str
    account_type: Optional[str] = None
    api_key: Optional[str] = None
    auth_token: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[int] = None
    scopes: Optional[List[str]] = None
    user_id: Optional[str] = None
    email: Optional[str] = None
    device_id: Optional[str] = None
    mfa_required: Optional[bool] = None
    mfa_verified: Optional[bool] = None
    oauth_api_key: Optional[str] = None
    oauth_api_key_expires_at: Optional[int] = None


class AuthManager:
    """Handle auth initialization and persistence."""

    def __init__(self, config_dir: Optional[str] = None) -> None:
        self.config_dir = pathlib.Path(
            config_dir or os.environ.get("CLAUDE_CONFIG_DIR", pathlib.Path.home() / ".claude")
        )
        self.auth_file = self.config_dir / "auth.json"
        self.credentials_file = self.config_dir / "credentials.json"
        self.official_config_file = self.config_dir / "config.json"
        self.official_credentials_file = self.config_dir / ".credentials.json"
        self.current_auth: Optional[AuthConfig] = None

    def _encrypt(self, value: str) -> str:
        key = hashlib.sha256((platform.node() + getpass.getuser()).encode("utf-8")).digest()
        data = value.encode("utf-8")
        encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
        return base64.b64encode(encrypted).decode("utf-8")

    def _decrypt(self, value: str) -> str:
        key = hashlib.sha256((platform.node() + getpass.getuser()).encode("utf-8")).digest()
        data = base64.b64decode(value.encode("utf-8"))
        decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
        return decrypted.decode("utf-8")

    def _save_auth_secure(self, auth: AuthConfig) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        payload: Dict[str, Any] = asdict(auth)
        for field in ("api_key", "access_token", "refresh_token"):
            if payload.get(field):
                payload[field] = self._encrypt(payload[field])
                payload[f"{field}_encrypted"] = True
        self.auth_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_auth_secure(self) -> Optional[AuthConfig]:
        if not self.auth_file.exists():
            return None
        try:
            data = json.loads(self.auth_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AuthError(f"Failed to parse auth file: {exc}") from exc
        for field in ("api_key", "access_token", "refresh_token"):
            if data.get(f"{field}_encrypted") and data.get(field):
                data[field] = self._decrypt(data[field])
                data.pop(f"{field}_encrypted", None)
        return AuthConfig(**data)

    def init_auth(self) -> Optional[AuthConfig]:
        env_api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
        if env_api_key:
            self.current_auth = AuthConfig(
                type="api_key",
                account_type="api",
                api_key=env_api_key,
                mfa_required=False,
                mfa_verified=True,
            )
            return self.current_auth

        if self.official_credentials_file.exists():
            try:
                creds = json.loads(self.official_credentials_file.read_text(encoding="utf-8"))
                oauth = creds.get("claudeAiOauth") or {}
                if oauth.get("accessToken") and "user:inference" in (oauth.get("scopes") or []):
                    self.current_auth = AuthConfig(
                        type="oauth",
                        account_type="subscription",
                        auth_token=oauth.get("accessToken"),
                        access_token=oauth.get("accessToken"),
                        refresh_token=oauth.get("refreshToken"),
                        expires_at=oauth.get("expiresAt"),
                        scopes=oauth.get("scopes"),
                        mfa_required=False,
                        mfa_verified=True,
                    )
                    return self.current_auth
            except json.JSONDecodeError:
                pass

        if self.official_config_file.exists():
            try:
                config = json.loads(self.official_config_file.read_text(encoding="utf-8"))
                if config.get("primaryApiKey"):
                    self.current_auth = AuthConfig(
                        type="api_key",
                        account_type="api",
                        api_key=config.get("primaryApiKey"),
                        mfa_required=False,
                        mfa_verified=True,
                    )
                    return self.current_auth
            except json.JSONDecodeError:
                pass

        if self.credentials_file.exists():
            try:
                creds = json.loads(self.credentials_file.read_text(encoding="utf-8"))
                if creds.get("apiKey"):
                    self.current_auth = AuthConfig(
                        type="api_key",
                        account_type="api",
                        api_key=creds.get("apiKey"),
                        mfa_required=False,
                        mfa_verified=True,
                    )
                    return self.current_auth
            except json.JSONDecodeError:
                pass

        auth = self._load_auth_secure()
        if auth:
            self.current_auth = auth
            return auth

        return None

    def get_api_key(self) -> Optional[str]:
        if not self.current_auth:
            return None
        if self.current_auth.type == "api_key":
            return self.current_auth.api_key
        if self.current_auth.type == "oauth":
            return self.current_auth.oauth_api_key
        return None

    def set_api_key(self, api_key: str, persist: bool = False) -> None:
        self.current_auth = AuthConfig(type="api_key", account_type="api", api_key=api_key)
        if persist:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            self.credentials_file.write_text(
                json.dumps({"apiKey": api_key}, indent=2),
                encoding="utf-8",
            )

    def create_oauth_api_key(self, access_token: str) -> Optional[str]:
        url = "https://api.anthropic.com/api/oauth/claude_cli/create_api_key"
        payload = json.dumps({}).encode("utf-8")
        req = urlrequest.Request(
            url,
            data=payload,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        )
        try:
            with urlrequest.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - network errors
            raise AuthError(f"Failed to create OAuth API key: {exc}") from exc
        return data.get("raw_key")


def init_auth(config_dir: Optional[str] = None) -> Optional[AuthConfig]:
    manager = AuthManager(config_dir=config_dir)
    return manager.init_auth()
