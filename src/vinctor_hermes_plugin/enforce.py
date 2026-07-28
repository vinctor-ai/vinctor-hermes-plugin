from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EnforceOutcome:
    decision: str
    audit_event_id: str | None = None


class ActionDeniedError(Exception):
    def __init__(self, reason: str = "action_denied", audit_event_id: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.audit_event_id = audit_event_id


class ServiceUnavailableError(Exception):
    reason = "service_unavailable"


class EnforceClient:
    def __init__(
        self,
        *,
        endpoint: str,
        agent_key: str,
        boundary_id: str | None = None,
        timeout_ms: int = 500,
        opener=urllib.request.urlopen,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.agent_key = agent_key
        self.boundary_id = boundary_id
        self.timeout_seconds = timeout_ms / 1000
        self.opener = opener

    def enforce(self, grant_ref: str, action: str, resource: str) -> EnforceOutcome:
        body = {
            "grant_ref": grant_ref,
            "action": action,
            "resource": resource,
        }
        headers = {
            "Content-Type": "application/json",
            "X-Agent-Key": self.agent_key,
        }
        if self.boundary_id:
            headers["X-Vinctor-Boundary-Id"] = self.boundary_id
        request = urllib.request.Request(
            f"{self.endpoint}/v1/enforce",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                payload = _read_json(response.read())
                if response.status == 200:
                    if _string_field(payload, "decision") != "permit":
                        raise ServiceUnavailableError("missing permit decision")
                    # PKA-116: a permit must carry durable decision evidence.
                    # Require a string audit_event_id with an ASCII alphanumeric
                    # (parity with the other adapters); a missing/null/empty/non-string id fails
                    # closed so a malformed or compromised 200 can't authorize an
                    # auditless action.
                    # Language-native trim/strip sets differ, so the shared
                    # positive rule avoids Unicode visually-blank differentials.
                    audit_event_id = _string_field(payload, "audit_event_id")
                    if not audit_event_id or re.search(r"[A-Za-z0-9]", audit_event_id) is None:
                        raise ServiceUnavailableError("permit without audit_event_id")
                    return EnforceOutcome(
                        decision="permit",
                        audit_event_id=audit_event_id,
                    )
                raise ServiceUnavailableError(f"unexpected status {response.status}")
        except urllib.error.HTTPError as exc:
            payload = _read_json(exc.read())
            if exc.code == 403:
                raise ActionDeniedError(
                    _string_field(payload, "error") or "action_denied",
                    _string_field(payload, "audit_event_id"),
                ) from exc
            raise ServiceUnavailableError(f"unexpected status {exc.code}") from exc
        except (OSError, TimeoutError) as exc:
            raise ServiceUnavailableError(str(exc)) from exc


def _read_json(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _string_field(payload: dict[str, Any], name: str) -> str | None:
    value = payload.get(name)
    return value if isinstance(value, str) else None
