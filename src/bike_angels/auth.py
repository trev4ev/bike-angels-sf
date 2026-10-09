from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import (
    BASE_URL,
    CLIENT_ID,
    CLIENT_SECRET,
    TOKEN_PATH,
    USER_AGENT,
    USER_DEVICE,
)


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None
    token_type: str = "Bearer"

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= (self.expires_at - 60)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenBundle:
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=data.get("expires_at"),
            token_type=data.get("token_type", "Bearer"),
        )


class AuthClient:
    """Lyft / Bay Wheels phone OTP authentication."""

    def __init__(self, token_path: Path = TOKEN_PATH) -> None:
        self.token_path = token_path
        self._device_id = str(uuid.uuid4()).upper()
        self._bundle_id = str(uuid.uuid4()).upper()
        self._client_session_id = str(uuid.uuid4()).upper()
        self._http = httpx.Client(timeout=30.0)
        self.tokens: TokenBundle | None = self.load_tokens()

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> AuthClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _basic_auth(self) -> str:
        raw = f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def _session_header(self, authenticated: bool = False) -> str:
        payload = {
            "j": self._device_id,
            "i": authenticated,
            "b": self._bundle_id,
            "e": "00000000-0000-0000-0000-000000000000",
        }
        return base64.b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).decode()

    def common_headers(self, authenticated: bool = False) -> dict[str, str]:
        headers = {
            "user-agent": USER_AGENT,
            "user-device": USER_DEVICE,
            "x-design-id": "x",
            "x-timestamp-ms": str(int(time.time() * 1000)),
            "x-locale-language": "en",
            "x-locale-region": "US",
            "accept-language": "en_US",
            "x-distance-unit": "miles",
            "x-device-density": "3.0",
            "x-client-session-id": self._client_session_id,
            "x-session": self._session_header(authenticated=authenticated),
            "x-timestamp-source": "system",
            "accept": "application/json",
        }
        return headers

    def get_anonymous_token(self) -> str:
        headers = self.common_headers()
        headers.update(
            {
                "authorization": self._basic_auth(),
                "content-type": "application/x-www-form-urlencoded; charset=utf-8",
            }
        )
        resp = self._http.post(
            f"{BASE_URL}/oauth2/access_token",
            content="grant_type=client_credentials",
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def request_code(self, phone_number: str) -> None:
        anon = self.get_anonymous_token()
        headers = self.common_headers()
        headers.update(
            {
                "authorization": f"Bearer {anon}",
                "content-type": "application/json",
                "x-idl-source": "pb.api.endpoints.v1.phone_auth.CreatePhoneAuthRequest",
                "accept": "application/x-protobuf,application/json",
            }
        )
        resp = self._http.post(
            f"{BASE_URL}/v1/phoneauth",
            json={"phone_number": phone_number, "voice_verification": False},
            headers=headers,
        )
        if resp.status_code not in (200, 202):
            raise RuntimeError(
                f"phoneauth failed: {resp.status_code} {resp.text}"
            )

    def login(
        self,
        phone_number: str,
        code: str,
        email: str | None = None,
    ) -> TokenBundle:
        headers = self.common_headers()
        headers.update(
            {
                "authorization": self._basic_auth(),
                "content-type": "application/x-www-form-urlencoded; charset=utf-8",
            }
        )
        form: dict[str, str] = {
            "grant_type": "urn:lyft:oauth2:grant_type:phone",
            "phone_number": phone_number,
            "phone_code": code,
            "extend_token_lifetime": "true",
        }
        if email:
            form["challenge"] = "email_match"
            form["email"] = email

        resp = self._http.post(
            f"{BASE_URL}/oauth2/access_token",
            content=urlencode(form),
            headers=headers,
        )
        if resp.status_code != 200:
            data = _safe_json(resp)
            if data.get("error") == "challenge_required":
                hint = ""
                for challenge in data.get("challenges", []):
                    if challenge.get("identifier") == "email_match":
                        hint = challenge.get("data", "")
                raise RuntimeError(
                    "Email verification required. Re-run login with --email "
                    f"matching hint: {hint or data}"
                )
            raise RuntimeError(f"login failed: {resp.status_code} {resp.text}")

        data = resp.json()
        expires_in = data.get("expires_in")
        bundle = TokenBundle(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=time.time() + expires_in if expires_in else None,
            token_type=data.get("token_type", "Bearer"),
        )
        self.tokens = bundle
        self.save_tokens()
        return bundle

    def refresh(self) -> TokenBundle:
        if not self.tokens or not self.tokens.refresh_token:
            raise RuntimeError("No refresh token stored; run login first")

        headers = self.common_headers(authenticated=True)
        headers.update(
            {
                "authorization": self._basic_auth(),
                "content-type": "application/x-www-form-urlencoded; charset=utf-8",
            }
        )
        form = urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": self.tokens.refresh_token,
            }
        )
        resp = self._http.post(
            f"{BASE_URL}/oauth2/access_token",
            content=form,
            headers=headers,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"refresh failed: {resp.status_code} {resp.text}")

        data = resp.json()
        expires_in = data.get("expires_in")
        bundle = TokenBundle(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", self.tokens.refresh_token),
            expires_at=time.time() + expires_in if expires_in else None,
            token_type=data.get("token_type", "Bearer"),
        )
        self.tokens = bundle
        self.save_tokens()
        return bundle

    def ensure_access_token(self) -> str:
        if not self.tokens:
            raise RuntimeError("Not logged in. Run: bike-angels login")
        if self.tokens.is_expired:
            self.refresh()
        assert self.tokens is not None
        return self.tokens.access_token

    def load_tokens(self) -> TokenBundle | None:
        if not self.token_path.exists():
            return None
        data = json.loads(self.token_path.read_text())
        return TokenBundle.from_dict(data)

    def save_tokens(self) -> None:
        if not self.tokens:
            return
        self.token_path.write_text(json.dumps(self.tokens.to_dict(), indent=2))
        self.token_path.chmod(0o600)


def _safe_json(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
