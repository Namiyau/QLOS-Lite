from __future__ import annotations

import json
import urllib.request
from typing import Any


def _id_for_api(value: str) -> int | str:
    text = str(value)
    try:
        return int(text)
    except ValueError:
        return text


class OneBotClient:
    def __init__(self, base_url: str, access_token: str | None = None, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token or ""
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
        retcode = data.get("retcode")
        status = str(data.get("status") or "")
        if (retcode is not None and retcode != 0) or (status and status != "ok"):
            raise OneBotSendError(endpoint, data)
        return data

    def send_private_msg(self, user_id: str, message: str) -> dict[str, Any]:
        return self._post("send_private_msg", {"user_id": _id_for_api(user_id), "message": message})

    def send_group_msg(self, group_id: str, message: str) -> dict[str, Any]:
        return self._post("send_group_msg", {"group_id": _id_for_api(group_id), "message": message})

    def upload_private_file(self, user_id: str, file_path: str, name: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"user_id": _id_for_api(user_id), "file": file_path}
        if name:
            payload["name"] = name
        return self._post("upload_private_file", payload)

    def upload_group_file(self, group_id: str, file_path: str, name: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"group_id": _id_for_api(group_id), "file": file_path}
        if name:
            payload["name"] = name
        return self._post("upload_group_file", payload)

    def get_file(self, file_id: str) -> dict[str, Any]:
        data = self._post("get_file", {"file_id": file_id})
        payload = data.get("data")
        return payload if isinstance(payload, dict) else data


class OneBotSendError(RuntimeError):
    def __init__(self, endpoint: str, response: dict[str, Any]):
        self.endpoint = endpoint
        self.response = response
        retcode = response.get("retcode")
        wording = response.get("wording") or response.get("message") or response.get("msg") or "send failed"
        super().__init__(f"OneBot {endpoint} failed: retcode={retcode} {wording}")
