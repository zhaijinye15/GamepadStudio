"""Gamepad Studio 社区后端：FastAPI + SQLite，单机即可跑.

接口一览（全部 /api 前缀）：
  GET  /api/health                       探活
  POST /api/register {username,password} 注册，返回 token / user(uid,badge)
  POST /api/login    {username,password} 登录
  GET  /api/me                           当前用户
  GET  /api/profile/{uid}                查某个 UID 的资料
  GET  /api/posts?limit&offset&kind      帖子列表
  POST /api/posts    {title,content,kind} 发帖
  GET  /api/posts/{id}                   帖子详情 + 评论
  POST /api/posts/{id}/comments {content} 回帖
  POST /api/posts/{id}/like              点赞 / 取消点赞
  GET  /api/stats                        用户数 / 帖子数

UID 标识规则（方案 C）：
  black  —— 管理员名单（环境变量 GS_ADMIN_UIDS）或 role=admin
  gold   —— 靓号：1~3 位 / 豹子号（同数字）/ 连号 / 整千整万
  normal —— 其它
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

DB_PATH = os.environ.get("GS_COMMUNITY_DB", "/opt/gamepad-community/data/community.db")
ADMIN_UIDS = {
    int(x) for x in os.environ.get("GS_ADMIN_UIDS", "").replace("，", ",").split(",") if x.strip().isdigit()
}
TOKEN_DAYS = 30
PW_ROUNDS = 120_000


def admin_uid_list() -> str:
    """后台展示用的名单原文，改环境变量重启即生效."""
    return os.environ.get("GS_ADMIN_UIDS", "").strip()

# 个性化：称号 / 签名长度上限，配色白名单（客户端同一份色板）
TITLE_MAX = 8
BIO_MAX = 40
PALETTE = (
    "",         # 默认
    "#D4A84A",  # 金
    "#4A9EE0",  # 蓝
    "#43C08A",  # 绿
    "#E0685E",  # 红
    "#A66BD4",  # 紫
    "#E08CB4",  # 粉
    "#E0A33C",  # 橙
    "#5FB7C7",  # 青
)

app = FastAPI(title="Gamepad Studio Community", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ 数据库
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              uid        INTEGER PRIMARY KEY AUTOINCREMENT,
              username   TEXT NOT NULL UNIQUE,
              pw_hash    TEXT NOT NULL,
              role       TEXT NOT NULL DEFAULT 'user',
              created_at INTEGER NOT NULL,
              title      TEXT NOT NULL DEFAULT '',
              bio        TEXT NOT NULL DEFAULT '',
              color      TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS tokens (
              token      TEXT PRIMARY KEY,
              uid        INTEGER NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
              created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS posts (
              id         INTEGER PRIMARY KEY AUTOINCREMENT,
              uid        INTEGER NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
              title      TEXT NOT NULL,
              content    TEXT NOT NULL,
              kind       TEXT NOT NULL DEFAULT 'talk',
              created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS comments (
              id         INTEGER PRIMARY KEY AUTOINCREMENT,
              post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
              uid        INTEGER NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
              content    TEXT NOT NULL,
              created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS likes (
              post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
              uid        INTEGER NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
              created_at INTEGER NOT NULL,
              PRIMARY KEY (post_id, uid)
            );
            CREATE TABLE IF NOT EXISTS admin_log (
              id         INTEGER PRIMARY KEY AUTOINCREMENT,
              ts         INTEGER NOT NULL,
              action     TEXT NOT NULL,
              detail     TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS notices (
              id         INTEGER PRIMARY KEY AUTOINCREMENT,
              text       TEXT NOT NULL,
              level      TEXT NOT NULL DEFAULT 'info',
              active     INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL
            );
            """
        )
        # UID 从 1001 开始，方便记
        conn.execute(
            "INSERT OR IGNORE INTO sqlite_sequence(name, seq) VALUES ('users', 1000)"
        )
        # 老库补列：个性化字段（称号 / 签名 / 配色）
        have = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        for col in ("title", "bio", "color", "badge_override"):
            if col not in have:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        if "banned" not in have:
            conn.execute("ALTER TABLE users ADD COLUMN banned INTEGER NOT NULL DEFAULT 0")


init_db()


# ------------------------------------------------------------------ 工具
def hash_pw(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PW_ROUNDS)
    return f"pbkdf2${PW_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_pw(password: str, stored: str) -> bool:
    try:
        _algo, rounds, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def badge_for(uid: int, role: str, override: str = "") -> str:
    """方案 C：黑色 = 管理员名单，金色 = 靓号，其它普通；后台 override 优先."""
    if override == "black":
        return "black"
    if override == "gold":
        return "gold"
    if role == "admin" or uid in ADMIN_UIDS:
        return "black"
    digits = str(uid)
    if len(digits) <= 3:
        return "gold"
    if len(set(digits)) == 1:                                   # 豹子号 8888 / 66666
        return "gold"
    if digits.endswith("000") or digits.endswith("0000"):       # 整千整万
        return "gold"
    if digits in {"1234", "12345", "123456", "1234567", "2345",
                  "3456", "4567", "5678", "6789"}:              # 连号
        return "gold"
    if len(digits) == 4 and digits[0] == digits[1] and digits[2] == digits[3]:
        return "gold"                                            # 1122 这种双对
    return "normal"


def new_token(conn: sqlite3.Connection, uid: int) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    conn.execute(
        "INSERT INTO tokens(token, uid, created_at, expires_at) VALUES (?,?,?,?)",
        (token, uid, now, now + TOKEN_DAYS * 86400),
    )
    return token


def current_uid(authorization: Optional[str] = Header(None)) -> int:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "缺少登录凭证")
    token = authorization.split(" ", 1)[1].strip()
    with db() as conn:
        row = conn.execute("SELECT uid, expires_at FROM tokens WHERE token=?", (token,)).fetchone()
    if not row:
        raise HTTPException(401, "登录已失效，请重新登录")
    if row["expires_at"] < int(time.time()):
        raise HTTPException(401, "登录已过期，请重新登录")
    return int(row["uid"])


def user_row(conn: sqlite3.Connection, uid: int):
    return conn.execute(
        "SELECT uid, username, role, created_at, title, bio, color, badge_override FROM users WHERE uid=?",
        (uid,),
    ).fetchone()


def _pick(row, key: str) -> str:
    try:
        return str(row[key] or "")
    except (IndexError, KeyError, TypeError):
        return ""


def public_user(row) -> dict:
    return {
        "uid": row["uid"],
        "username": row["username"],
        "badge": badge_for(row["uid"], row["role"], _pick(row, "badge_override")),
        "role": row["role"],
        "created_at": row["created_at"],
        "title": _pick(row, "title"),
        "bio": _pick(row, "bio"),
        "color": _pick(row, "color"),
    }


def author_of(row, title_key: str = "title", color_key: str = "color",
              badge_key: str = "badge_override") -> dict:
    return {
        "uid": row["uid"],
        "username": row["username"],
        "badge": badge_for(row["uid"], row["role"], _pick(row, badge_key)),
        "title": _pick(row, title_key),
        "color": _pick(row, color_key),
    }


# ------------------------------------------------------------------ 模型
class AuthIn(BaseModel):
    username: str = Field(min_length=2, max_length=20)
    password: str = Field(min_length=6, max_length=64)


class PostIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=4000)
    kind: str = Field(default="talk", max_length=20)


class CommentIn(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


class ProfileIn(BaseModel):
    """个性化字段；全部可选，只改传上来的那一项."""
    title: Optional[str] = None
    bio: Optional[str] = None
    color: Optional[str] = None


# ------------------------------------------------------------------ 接口
@app.get("/api/health")
def health():
    with db() as conn:
        users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    return {"ok": True, "time": int(time.time()), "users": users, "service": "gamepad-community"}


@app.post("/api/register")
def register(data: AuthIn):
    username = data.username.strip()
    if not username:
        raise HTTPException(400, "用户名不能为空")
    with db() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users(username, pw_hash, role, created_at) VALUES (?,?,?,?)",
                (username, hash_pw(data.password), "user", int(time.time())),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "这个用户名已经被注册了")
        uid = int(cur.lastrowid)
        token = new_token(conn, uid)
        row = user_row(conn, uid)
    return {"token": token, "user": public_user(row)}


@app.post("/api/login")
def login(data: AuthIn):
    with db() as conn:
        row = conn.execute(
            "SELECT uid, username, pw_hash, role, created_at, title, bio, color, badge_override, banned FROM users WHERE username=?",
            (data.username.strip(),),
        ).fetchone()
        if not row or not verify_pw(data.password, row["pw_hash"]):
            raise HTTPException(401, "用户名或密码不对")
        if row["banned"]:
            raise HTTPException(403, "这个账号已被封禁")
        token = new_token(conn, int(row["uid"]))
    return {"token": token, "user": public_user(row)}


@app.get("/api/me")
def me(uid: int = Depends(current_uid)):
    with db() as conn:
        row = user_row(conn, uid)
    if not row:
        raise HTTPException(404, "用户不存在")
    return public_user(row)


@app.get("/api/profile/{uid}")
def profile(uid: int):
    with db() as conn:
        row = user_row(conn, uid)
        if not row:
            raise HTTPException(404, "用户不存在")
        posts = conn.execute("SELECT COUNT(*) c FROM posts WHERE uid=?", (uid,)).fetchone()["c"]
    data = public_user(row)
    data["posts"] = posts
    return data


@app.patch("/api/me")
def update_me(data: ProfileIn, uid: int = Depends(current_uid)):
    """个性化：称号 / 签名 / 配色. 只改传上来的字段."""
    title = data.title.strip() if data.title is not None else None
    bio = data.bio.strip() if data.bio is not None else None
    color = data.color.strip().upper() if data.color is not None else None
    if title is not None and len(title) > TITLE_MAX:
        raise HTTPException(400, f"称号最多 {TITLE_MAX} 个字")
    if bio is not None and len(bio) > BIO_MAX:
        raise HTTPException(400, f"签名最多 {BIO_MAX} 个字")
    if color is not None and color and color not in PALETTE:
        raise HTTPException(400, "这个颜色不在可选范围里")
    with db() as conn:
        if title is not None:
            conn.execute("UPDATE users SET title=? WHERE uid=?", (title, uid))
        if bio is not None:
            conn.execute("UPDATE users SET bio=? WHERE uid=?", (bio, uid))
        if color is not None:
            conn.execute("UPDATE users SET color=? WHERE uid=?", (color, uid))
        row = user_row(conn, uid)
    return public_user(row)


@app.get("/api/posts")
def list_posts(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), kind: Optional[str] = None):
    sql = (
        "SELECT p.id, p.uid, p.title, p.content, p.kind, p.created_at, u.username, u.role, u.title AS t,"
        " u.color AS c, u.badge_override AS b,"
        " (SELECT COUNT(*) FROM likes l WHERE l.post_id=p.id) likes,"
        " (SELECT COUNT(*) FROM comments c2 WHERE c2.post_id=p.id) comments"
        " FROM posts p JOIN users u ON u.uid=p.uid"
    )
    params: list = []
    if kind:
        sql += " WHERE p.kind=?"
        params.append(kind)
    sql += " ORDER BY p.id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
        notice = None
        if offset == 0 and not kind:
            notice = conn.execute(
                "SELECT text, level, created_at FROM notices WHERE active=1 ORDER BY id DESC LIMIT 1"
            ).fetchone()
    payload = {
        "total": len(rows),
        "notice": dict(notice) if notice else None,
        "items": [
            {
                "id": r["id"],
                "title": r["title"],
                "content": r["content"],
                "kind": r["kind"],
                "created_at": r["created_at"],
                "likes": r["likes"],
                "comments": r["comments"],
                "author": author_of(r, "t", "c", "b"),
            }
            for r in rows
        ],
    }
    return with_notice(payload)


def with_notice(payload: dict) -> dict:
    """把生效中的公告当成一条置顶条目塞进列表，1.3.3 客户端不用更新也能看见."""
    notice = payload.get("notice")
    if notice:
        pinned = {
            "id": 0,
            "title": ("📢 " if notice.get("level") != "warn" else "❗ ") + str(notice.get("text", "")),
            "content": "",
            "kind": "notice",
            "created_at": int(notice.get("created_at") or 0),
            "likes": 0,
            "comments": 0,
            "author": {"uid": 0, "username": "系统公告", "badge": "black", "title": "", "color": "#D4A84A"},
        }
        payload["items"] = [pinned] + list(payload.get("items", []))
    return payload


@app.post("/api/posts")
def create_post(data: PostIn, uid: int = Depends(current_uid)):
    with db() as conn:
        if conn.execute("SELECT banned FROM users WHERE uid=?", (uid,)).fetchone()["banned"]:
            raise HTTPException(403, "账号已被封禁，不能发帖")
        cur = conn.execute(
            "INSERT INTO posts(uid, title, content, kind, created_at) VALUES (?,?,?,?,?)",
            (uid, data.title.strip(), data.content.strip(), data.kind or "talk", int(time.time())),
        )
        pid = int(cur.lastrowid)
    return {"ok": True, "id": pid}


@app.get("/api/posts/{post_id}")
def get_post(post_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT p.id, p.uid, p.title, p.content, p.kind, p.created_at, u.username, u.role,"
            " u.title AS t, u.color AS c, u.badge_override AS b"
            " FROM posts p JOIN users u ON u.uid=p.uid WHERE p.id=?",
            (post_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "帖子不存在")
        comments = conn.execute(
            "SELECT c.id, c.uid, c.content, c.created_at, u.username, u.role, u.title AS t,"
            " u.color AS c2, u.badge_override AS b2"
            " FROM comments c JOIN users u ON u.uid=c.uid WHERE c.post_id=? ORDER BY c.id ASC",
            (post_id,),
        ).fetchall()
        likes = conn.execute("SELECT COUNT(*) c FROM likes WHERE post_id=?", (post_id,)).fetchone()["c"]
    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "kind": row["kind"],
        "created_at": row["created_at"],
        "likes": likes,
        "author": author_of(row, "t", "c", "b"),
        "comments": [
            {
                "id": c["id"],
                "content": c["content"],
                "created_at": c["created_at"],
                "author": author_of(c, "t", "c2", "b2"),
            }
            for c in comments
        ],
    }


@app.post("/api/posts/{post_id}/comments")
def add_comment(post_id: int, data: CommentIn, uid: int = Depends(current_uid)):
    with db() as conn:
        if conn.execute("SELECT banned FROM users WHERE uid=?", (uid,)).fetchone()["banned"]:
            raise HTTPException(403, "账号已被封禁，不能评论")
        if not conn.execute("SELECT 1 FROM posts WHERE id=?", (post_id,)).fetchone():
            raise HTTPException(404, "帖子不存在")
        conn.execute(
            "INSERT INTO comments(post_id, uid, content, created_at) VALUES (?,?,?,?)",
            (post_id, uid, data.content.strip(), int(time.time())),
        )
    return {"ok": True}


@app.post("/api/posts/{post_id}/like")
def toggle_like(post_id: int, uid: int = Depends(current_uid)):
    if post_id == 0:      # 0 是服务端注入的公告条，点赞无意义
        return {"ok": True, "liked": False, "likes": 0}
    with db() as conn:
        if not conn.execute("SELECT 1 FROM posts WHERE id=?", (post_id,)).fetchone():
            raise HTTPException(404, "帖子不存在")
        existing = conn.execute("SELECT 1 FROM likes WHERE post_id=? AND uid=?", (post_id, uid)).fetchone()
        if existing:
            conn.execute("DELETE FROM likes WHERE post_id=? AND uid=?", (post_id, uid))
            liked = False
        else:
            conn.execute("INSERT INTO likes(post_id, uid, created_at) VALUES (?,?,?)",
                         (post_id, uid, int(time.time())))
            liked = True
        total = conn.execute("SELECT COUNT(*) c FROM likes WHERE post_id=?", (post_id,)).fetchone()["c"]
    return {"ok": True, "liked": liked, "likes": total}


@app.get("/api/notice")
def current_notice():
    """当前生效的公告；客户端和官网都能读，没有就返回 null."""
    with db() as conn:
        row = conn.execute(
            "SELECT text, level, created_at FROM notices WHERE active=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return {"notice": None}
    return {"notice": {"text": row["text"], "level": row["level"], "created_at": row["created_at"]}}


@app.get("/api/stats")
def stats():
    with db() as conn:
        users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        posts = conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"]
        comments = conn.execute("SELECT COUNT(*) c FROM comments").fetchone()["c"]
    return {"users": users, "posts": posts, "comments": comments}


import admin_panel  # noqa: E402

admin_panel.bind(db, badge_for, admin_uid_list)
app.include_router(admin_panel.router)


@app.get("/", response_class=HTMLResponse)
def index():
    with db() as conn:
        users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        posts = conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"]
    return f"""<!doctype html><meta charset="utf-8"><title>Gamepad Studio 社区</title>
<body style="font-family:system-ui;background:#0b0f14;color:#dfe8f5;padding:40px">
<h2>Gamepad Studio 社区 · 服务在线</h2>
<p>注册用户 {users} · 帖子 {posts}</p>
<p>接口文档：<a style="color:#19c37d" href="/docs">/docs</a></p>
</body>"""
