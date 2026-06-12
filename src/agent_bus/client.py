from __future__ import annotations

import os
from typing import Any

import requests


class AgentBusClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, timeout: float = 30.0):
        self.base_url = (base_url or os.environ.get("AGENT_BUS_URL") or "http://127.0.0.1:8765").rstrip("/")
        self.token = token if token is not None else os.environ.get("AGENT_BUS_TOKEN")
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        url = f"{self.base_url}{path}"
        response = requests.request(method, url, json=payload, headers=headers, timeout=self.timeout)
        try:
            data = response.json()
        except ValueError:
            data = {"error": response.text}
        if response.status_code >= 400:
            raise RuntimeError(f"{response.status_code} {data.get('error', response.text)}")
        return data

    def get(self, path: str) -> dict[str, Any]:
        return self.request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", path, payload)
