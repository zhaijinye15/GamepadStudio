"""社区客户端：注册 / 登录 / 发帖 / 点赞，走本机 urllib，不引第三方依赖."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_BASE = "http://8.217.155.133"
TIMEOUT = 12


class CommunityError(Exception):
    """接口返回的错误，message 直接给用户看."""


class CommunityClient:
    """一个轻量的 REST 客户端；token 落盘到 %APPDATA%\\GamepadStudio\\community.json."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or (Path(os.environ.get("APPDATA", ".")) / "GamepadStudio" / "community.json")
        self.base = DEFAULT_BASE
        self.token = ""
        self.user: Dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------ 持久化
    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            self.base = data.get("base") or DEFAULT_BASE
            self.token = data.get("token") or ""
            user = data.get("user")
            self.user = user if isinstance(user, dict) else {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"base": self.base, "token": self.token, "user": self.user}
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------ HTTP
    def _request(self, method: str, path: str, body: Optional[dict] = None,
                 auth: bool = False) -> Any:
        url = self.base.rstrip("/") + path
        data = None
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8", "replace")).get("detail")
            except (ValueError, OSError):
                detail = None
            raise CommunityError(detail or f"请求失败（HTTP {exc.code}）") from None
        except urllib.error.URLError as exc:
            raise CommunityError(f"连不上社区服务器：{exc.reason}") from None
        except OSError as exc:
            raise CommunityError(f"网络异常：{exc}") from None
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            raise CommunityError("服务器返回的内容无法解析") from None

    # ------------------------------------------------------------ 账号
    def register(self, username: str, password: str) -> Dict[str, Any]:
        data = self._request("POST", "/api/register", {"username": username, "password": password})
        self._apply_auth(data)
        return data

    def login(self, username: str, password: str) -> Dict[str, Any]:
        data = self._request("POST", "/api/login", {"username": username, "password": password})
        self._apply_auth(data)
        return data

    def _apply_auth(self, data: Dict[str, Any]) -> None:
        self.token = data.get("token", "")
        self.user = data.get("user") or {}
        self._save()

    def logout(self) -> None:
        self.token = ""
        self.user = {}
        self._save()

    def refresh_me(self) -> Dict[str, Any]:
        if not self.token:
            raise CommunityError("还没有登录")
        self.user = self._request("GET", "/api/me", auth=True)
        self._save()
        return self.user

    # ------------------------------------------------------------ 社区
    def list_posts(self, limit: int = 30) -> List[Dict[str, Any]]:
        data = self._request("GET", f"/api/posts?limit={limit}")
        items = data.get("items") if isinstance(data, dict) else None
        return items or []

    def create_post(self, title: str, content: str, kind: str = "talk") -> int:
        data = self._request("POST", "/api/posts",
                             {"title": title, "content": content, "kind": kind}, auth=True)
        return int(data.get("id", 0))

    def like(self, post_id: int) -> Tuple[bool, int]:
        data = self._request("POST", f"/api/posts/{post_id}/like", {}, auth=True)
        return bool(data.get("liked")), int(data.get("likes", 0))

    def comment(self, post_id: int, content: str) -> None:
        self._request("POST", f"/api/posts/{post_id}/comments", {"content": content}, auth=True)

    def stats(self) -> Dict[str, Any]:
        return self._request("GET", "/api/stats")

    # ------------------------------------------------------------ 展示
    @property
    def badge(self) -> str:
        return str(self.user.get("badge", "normal"))

    @property
    def uid(self) -> int:
        try:
            return int(self.user.get("uid", 0))
        except (TypeError, ValueError):
            return 0

    @property
    def logged_in(self) -> bool:
        return bool(self.token and self.user)
