from __future__ import annotations

import requests


class RuntimeAPIClient:
    def __init__(self, *, base_url: str, token: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )

    def report_runtime_event(self, *, account_id: int, event_type: str, metadata: dict[str, object] | None = None):
        response = self.session.post(
            f"{self.base_url}/api/v1/accounts/{account_id}/runtime-events/",
            json={
                "event_type": event_type,
                "metadata": metadata or {},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
