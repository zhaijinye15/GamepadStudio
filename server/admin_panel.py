"""管理后台：/admin 网页 + JSON API.

单独一个模块，挂到主 app 上（include_router），不把 app.py 撑爆。
登录用一个 HMAC 签名 cookie，密码和密钥都来自环境变量：
  GS_ADMIN_PASS    管理员密码（不设则后台整体关闭）
  GS_ADMIN_SECRET  签名密钥（不设就每次重启随机，等于重启后要重新登录）
"""
from __future__ import annotations

import hmac
import hashlib
import json
import os
import secrets
import sqlite3
import tempfile
import time
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

router = APIRouter()

ADMIN_USER = os.environ.get("GS_ADMIN_USER", "admin").strip() or "admin"
ADMIN_PASS = os.environ.get("GS_ADMIN_PASS", "").strip()
ADMIN_SECRET = os.environ.get("GS_ADMIN_SECRET", "").strip() or secrets.token_hex(16)
COOKIE = "gs_admin"
TTL = 12 * 3600

_DB: Callable = None          # app.db 的 contextmanager
_BADGE: Callable = None       # app.badge_for
_UID_LIST: Callable = None    # app.admin_uid_list，读 GS_ADMIN_UIDS


def bind(db, badge_for, admin_uid_list) -> None:
    global _DB, _BADGE, _UID_LIST
    _DB, _BADGE, _UID_LIST = db, badge_for, admin_uid_list


# --------------------------------------------------------------------- 会话
def _sign(value: str) -> str:
    return hmac.new(ADMIN_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]


def _issue() -> str:
    ts = str(int(time.time()))
    return f"{ts}.{_sign(ts)}"


def _verify(token: str) -> bool:
    try:
        ts, sig = token.split(".", 1)
        if int(time.time()) - int(ts) > TTL:
            return False
        return hmac.compare_digest(sig, _sign(ts))
    except (ValueError, AttributeError):
        return False


def require_admin(request: Request) -> None:
    if not ADMIN_PASS:
        raise HTTPException(503, "后台没有配置管理员密码（GS_ADMIN_PASS）")
    if not _verify(request.cookies.get(COOKIE, "")):
        raise HTTPException(401, "请先登录")


def _log(conn: sqlite3.Connection, action: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO admin_log(ts, action, detail) VALUES (?,?,?)",
        (int(time.time()), action[:40], detail[:400]),
    )


def _iso(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts or 0)))


# --------------------------------------------------------------------- 登录
FAILS: dict = {}          # ip -> (失败次数, 首次失败时间)
FAIL_LIMIT = 6
FAIL_WINDOW = 600


def _guard(ip: str) -> None:
    """短密码的代价用试错锁补回来：10 分钟内错 6 次就锁."""
    count, since = FAILS.get(ip, (0, 0.0))
    if time.time() - since > FAIL_WINDOW:
        FAILS.pop(ip, None)
        return
    if count >= FAIL_LIMIT:
        left = int(FAIL_WINDOW - (time.time() - since))
        raise HTTPException(429, f"密码错太多次了，等 {max(1, left // 60)} 分钟再试")


def _note_fail(ip: str) -> None:
    count, since = FAILS.get(ip, (0, time.time()))
    if time.time() - since > FAIL_WINDOW:
        count, since = 0, time.time()
    FAILS[ip] = (count + 1, since)


@router.post("/admin/api/login")
async def admin_login(request: Request, response: Response):
    if not ADMIN_PASS:
        raise HTTPException(503, "后台没有配置管理员密码")
    try:
        body = await request.json()
    except Exception:
        body = {}
    ip = request.client.host if request.client else "?"
    _guard(ip)
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    if not (hmac.compare_digest(username, ADMIN_USER) and hmac.compare_digest(password, ADMIN_PASS)):
        _note_fail(ip)
        with _DB() as conn:
            _log(conn, "登录失败", f"{ip} user={username[:20]}")
        raise HTTPException(403, "用户名或密码不对")
    FAILS.pop(ip, None)
    response.set_cookie(COOKIE, _issue(), httponly=True, samesite="lax", max_age=TTL, path="/")
    with _DB() as conn:
        _log(conn, "登录成功", request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/api/logout")
def admin_logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/admin/api/whoami")
def whoami(request: Request):
    return {"ok": True, "admin": bool(ADMIN_PASS) and _verify(request.cookies.get(COOKIE, ""))}


# --------------------------------------------------------------------- 概览
@router.get("/admin/api/overview", dependencies=[Depends(require_admin)])
def overview():
    now = int(time.time())
    with _DB() as conn:
        users = conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        posts = conn.execute("SELECT COUNT(*) n FROM posts").fetchone()["n"]
        comments = conn.execute("SELECT COUNT(*) n FROM comments").fetchone()["n"]
        likes = conn.execute("SELECT COUNT(*) n FROM likes").fetchone()["n"]
        banned = conn.execute("SELECT COUNT(*) n FROM users WHERE banned=1").fetchone()["n"]
        today = conn.execute(
            "SELECT COUNT(*) n FROM users WHERE created_at > ?", (now - 86400,)
        ).fetchone()["n"]
        week = conn.execute(
            "SELECT COUNT(*) n FROM users WHERE created_at > ?", (now - 7 * 86400,)
        ).fetchone()["n"]
        certified = conn.execute(
            "SELECT COUNT(*) n FROM users WHERE badge_override='black'"
        ).fetchone()["n"]
        gold = conn.execute(
            "SELECT COUNT(*) n FROM users WHERE badge_override='gold'"
        ).fetchone()["n"]
        logs = [
            {"ts": _iso(r["ts"]), "action": r["action"], "detail": r["detail"]}
            for r in conn.execute(
                "SELECT ts, action, detail FROM admin_log ORDER BY id DESC LIMIT 20"
            ).fetchall()
        ]
        newest = [
            {"uid": r["uid"], "username": r["username"], "when": _iso(r["created_at"])}
            for r in conn.execute(
                "SELECT uid, username, created_at FROM users ORDER BY uid DESC LIMIT 5"
            ).fetchall()
        ]
        notice = conn.execute(
            "SELECT id, text, level FROM notices WHERE active=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {
        "users": users, "posts": posts, "comments": comments, "likes": likes,
        "banned": banned, "today": today, "week": week,
        "certified": certified, "gold": gold,
        "logs": logs, "newest": newest,
        "notice": dict(notice) if notice else None,
        "admin_uids": _UID_LIST(),
        "server_time": _iso(now),
    }


# --------------------------------------------------------------------- 用户
@router.get("/admin/api/users", dependencies=[Depends(require_admin)])
def list_users(q: str = "", page: int = 1, limit: int = 30):
    limit = max(1, min(200, limit))
    offset = (max(1, page) - 1) * limit
    like = f"%{q.strip()}%"
    with _DB() as conn:
        where = ""
        args: list = []
        if q.strip():
            where = "WHERE u.username LIKE ? OR CAST(u.uid AS TEXT) LIKE ? OR u.title LIKE ?"
            args = [like, like, like]
        total = conn.execute(f"SELECT COUNT(*) n FROM users u {where}", args).fetchone()["n"]
        rows = conn.execute(
            "SELECT u.uid, u.username, u.role, u.created_at, u.title, u.bio, u.color,"
            " u.badge_override, u.banned,"
            " (SELECT COUNT(*) FROM posts p WHERE p.uid=u.uid) posts,"
            " (SELECT COUNT(*) FROM comments c WHERE c.uid=u.uid) comments"
            f" FROM users u {where} ORDER BY u.uid DESC LIMIT ? OFFSET ?",
            args + [limit, offset],
        ).fetchall()
    items = []
    for r in rows:
        badge = _BADGE(r["uid"], r["role"], r["badge_override"] or "")
        items.append({
            "uid": r["uid"], "username": r["username"], "role": r["role"],
            "badge": badge, "badge_override": r["badge_override"] or "",
            "title": r["title"] or "", "bio": r["bio"] or "", "color": r["color"] or "",
            "banned": bool(r["banned"]), "posts": r["posts"], "comments": r["comments"],
            "created_at": _iso(r["created_at"]),
        })
    return {"total": total, "page": page, "limit": limit, "items": items}


@router.post("/admin/api/users/{uid}", dependencies=[Depends(require_admin)])
async def edit_user(uid: int, request: Request):
    body = await request.json()
    fields = {}
    if "username" in body:
        name = str(body["username"]).strip()
        if not (2 <= len(name) <= 20):
            raise HTTPException(400, "用户名 2–20 字符")
        fields["username"] = name
    if "title" in body:
        title = str(body["title"]).strip()
        if len(title) > 8:
            raise HTTPException(400, "称号最多 8 字")
        fields["title"] = title
    if "bio" in body:
        bio = str(body["bio"]).strip()
        if len(bio) > 40:
            raise HTTPException(400, "签名最多 40 字")
        fields["bio"] = bio
    if "color" in body:
        fields["color"] = str(body["color"]).strip().upper()
    if "badge_override" in body:
        value = str(body["badge_override"]).strip().lower()
        if value not in ("", "black", "gold"):
            raise HTTPException(400, "徽标只能是 认证 / 靓号 / 自动")
        fields["badge_override"] = value
    if "banned" in body:
        fields["banned"] = 1 if body["banned"] else 0
    if "role" in body:
        role = str(body["role"]).strip()
        if role not in ("user", "moderator"):
            raise HTTPException(400, "角色只能是 user / moderator")
        fields["role"] = role
    if not fields:
        raise HTTPException(400, "没有要改的字段")
    with _DB() as conn:
        row = conn.execute("SELECT uid FROM users WHERE uid=?", (uid,)).fetchone()
        if not row:
            raise HTTPException(404, "没有这个用户")
        sql = "UPDATE users SET " + ", ".join(f"{k}=?" for k in fields) + " WHERE uid=?"
        try:
            conn.execute(sql, list(fields.values()) + [uid])
        except sqlite3.IntegrityError:
            raise HTTPException(400, "用户名已经被占用了")
        _log(conn, "改用户", f"uid={uid} " + json.dumps(fields, ensure_ascii=False))
    return {"ok": True}


@router.delete("/admin/api/users/{uid}", dependencies=[Depends(require_admin)])
def delete_user(uid: int):
    with _DB() as conn:
        if not conn.execute("SELECT uid FROM users WHERE uid=?", (uid,)).fetchone():
            raise HTTPException(404, "没有这个用户")
        conn.execute("DELETE FROM likes WHERE post_id IN (SELECT id FROM posts WHERE uid=?)", (uid,))
        conn.execute("DELETE FROM likes WHERE uid=?", (uid,))
        conn.execute("DELETE FROM comments WHERE uid=? OR post_id IN (SELECT id FROM posts WHERE uid=?)", (uid, uid))
        conn.execute("DELETE FROM posts WHERE uid=?", (uid,))
        conn.execute("DELETE FROM users WHERE uid=?", (uid,))
        _log(conn, "删用户", f"uid={uid}")
    return {"ok": True}


# --------------------------------------------------------------------- 内容
@router.get("/admin/api/posts", dependencies=[Depends(require_admin)])
def list_posts(q: str = "", page: int = 1, limit: int = 30):
    limit = max(1, min(200, limit))
    offset = (max(1, page) - 1) * limit
    with _DB() as conn:
        where, args = "", []
        if q.strip():
            where = "WHERE p.title LIKE ? OR p.content LIKE ? OR u.username LIKE ?"
            args = [f"%{q.strip()}%"] * 3
        total = conn.execute(
            f"SELECT COUNT(*) n FROM posts p JOIN users u ON u.uid=p.uid {where}", args
        ).fetchone()["n"]
        rows = conn.execute(
            "SELECT p.id, p.uid, p.title, p.content, p.kind, p.created_at, u.username,"
            " (SELECT COUNT(*) FROM likes l WHERE l.post_id=p.id) likes,"
            " (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) comments"
            f" FROM posts p JOIN users u ON u.uid=p.uid {where} ORDER BY p.id DESC LIMIT ? OFFSET ?",
            args + [limit, offset],
        ).fetchall()
    return {
        "total": total, "page": page, "limit": limit,
        "items": [{
            "id": r["id"], "uid": r["uid"], "username": r["username"],
            "title": r["title"], "content": (r["content"] or "")[:200],
            "kind": r["kind"], "likes": r["likes"], "comments": r["comments"],
            "created_at": _iso(r["created_at"]),
        } for r in rows],
    }


@router.delete("/admin/api/posts/{pid}", dependencies=[Depends(require_admin)])
def delete_post(pid: int):
    with _DB() as conn:
        if not conn.execute("SELECT id FROM posts WHERE id=?", (pid,)).fetchone():
            raise HTTPException(404, "没有这个帖子")
        conn.execute("DELETE FROM likes WHERE post_id=?", (pid,))
        conn.execute("DELETE FROM comments WHERE post_id=?", (pid,))
        conn.execute("DELETE FROM posts WHERE id=?", (pid,))
        _log(conn, "删帖子", f"post={pid}")
    return {"ok": True}


@router.get("/admin/api/comments", dependencies=[Depends(require_admin)])
def list_comments(page: int = 1, limit: int = 40):
    limit = max(1, min(200, limit))
    offset = (max(1, page) - 1) * limit
    with _DB() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM comments").fetchone()["n"]
        rows = conn.execute(
            "SELECT c.id, c.post_id, c.uid, c.content, c.created_at, u.username, p.title post_title"
            " FROM comments c JOIN users u ON u.uid=c.uid LEFT JOIN posts p ON p.id=c.post_id"
            " ORDER BY c.id DESC LIMIT ? OFFSET ?", (limit, offset),
        ).fetchall()
    return {
        "total": total, "page": page, "limit": limit,
        "items": [{
            "id": r["id"], "post_id": r["post_id"], "post_title": r["post_title"] or "(已删除)",
            "uid": r["uid"], "username": r["username"], "content": r["content"],
            "created_at": _iso(r["created_at"]),
        } for r in rows],
    }


@router.delete("/admin/api/comments/{cid}", dependencies=[Depends(require_admin)])
def delete_comment(cid: int):
    with _DB() as conn:
        if not conn.execute("SELECT id FROM comments WHERE id=?", (cid,)).fetchone():
            raise HTTPException(404, "没有这条评论")
        conn.execute("DELETE FROM comments WHERE id=?", (cid,))
        _log(conn, "删评论", f"comment={cid}")
    return {"ok": True}


# --------------------------------------------------------------------- 公告
@router.get("/admin/api/notices", dependencies=[Depends(require_admin)])
def list_notices():
    with _DB() as conn:
        rows = conn.execute(
            "SELECT id, text, level, active, created_at FROM notices ORDER BY id DESC LIMIT 50"
        ).fetchall()
    return {"items": [{
        "id": r["id"], "text": r["text"], "level": r["level"],
        "active": bool(r["active"]), "created_at": _iso(r["created_at"]),
    } for r in rows]}


@router.post("/admin/api/notices", dependencies=[Depends(require_admin)])
async def add_notice(request: Request):
    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(400, "公告内容不能为空")
    if len(text) > 200:
        raise HTTPException(400, "公告最多 200 字")
    level = str(body.get("level", "info")).strip()
    if level not in ("info", "warn"):
        level = "info"
    with _DB() as conn:
        conn.execute("UPDATE notices SET active=0")
        conn.execute(
            "INSERT INTO notices(text, level, active, created_at) VALUES (?,?,1,?)",
            (text, level, int(time.time())),
        )
        _log(conn, "发公告", text)
    return {"ok": True}


@router.post("/admin/api/notices/{nid}/toggle", dependencies=[Depends(require_admin)])
async def toggle_notice(nid: int, request: Request):
    body = await request.json()
    active = 1 if body.get("active") else 0
    with _DB() as conn:
        if active:
            conn.execute("UPDATE notices SET active=0")
        conn.execute("UPDATE notices SET active=? WHERE id=?", (active, nid))
        _log(conn, "公告开关", f"id={nid} active={active}")
    return {"ok": True}


@router.delete("/admin/api/notices/{nid}", dependencies=[Depends(require_admin)])
def delete_notice(nid: int):
    with _DB() as conn:
        conn.execute("DELETE FROM notices WHERE id=?", (nid,))
        _log(conn, "删公告", f"id={nid}")
    return {"ok": True}


# --------------------------------------------------------------------- 数据
@router.get("/admin/api/logs", dependencies=[Depends(require_admin)])
def list_logs(page: int = 1, limit: int = 50):
    limit = max(1, min(200, limit))
    offset = (max(1, page) - 1) * limit
    with _DB() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM admin_log").fetchone()["n"]
        rows = conn.execute(
            "SELECT ts, action, detail FROM admin_log ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return {"total": total, "page": page, "items": [
        {"ts": _iso(r["ts"]), "action": r["action"], "detail": r["detail"]} for r in rows
    ]}


@router.get("/admin/api/export", dependencies=[Depends(require_admin)])
def export_data(kind: str = "users"):
    """导出 JSON：users / posts / comments."""
    with _DB() as conn:
        if kind == "posts":
            rows = [dict(r) for r in conn.execute(
                "SELECT p.*, u.username FROM posts p JOIN users u ON u.uid=p.uid ORDER BY p.id").fetchall()]
        elif kind == "comments":
            rows = [dict(r) for r in conn.execute(
                "SELECT c.*, u.username FROM comments c JOIN users u ON u.uid=c.uid ORDER BY c.id").fetchall()]
        else:
            rows = [dict(r) for r in conn.execute(
                "SELECT uid, username, role, created_at, title, bio, color, badge_override, banned"
                " FROM users ORDER BY uid").fetchall()]
    _log_async(kind)
    payload = json.dumps(rows, ensure_ascii=False, indent=2)
    return Response(payload, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="gs-{kind}.json"'})


def _log_async(kind: str) -> None:
    try:
        with _DB() as conn:
            _log(conn, "导出数据", kind)
    except Exception:
        pass


@router.get("/admin/api/backup", dependencies=[Depends(require_admin)])
def backup_db():
    """在线热备份：用 sqlite 自己的 backup 接口，避免直接拷正在写的库."""
    with _DB() as conn:
        tmp = tempfile.NamedTemporaryFile(prefix="gs-backup-", suffix=".db", delete=False)
        tmp.close()
        dst = sqlite3.connect(tmp.name)
        conn.backup(dst)
        dst.close()
        _log(conn, "下载备份", os.path.basename(tmp.name))
    data = open(tmp.name, "rb").read()
    os.unlink(tmp.name)
    name = "community-" + time.strftime("%Y%m%d-%H%M") + ".db"
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# --------------------------------------------------------------------- 页面
@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    if not ADMIN_PASS:
        return HTMLResponse("<h2 style='font:16px sans-serif;padding:40px'>后台未启用：服务器没有设置 GS_ADMIN_PASS</h2>", status_code=503)
    return HTMLResponse(HTML, headers={"Cache-Control": "no-store"})


HTML = r"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gamepad Studio · 管理后台</title>
<style>
:root{--bg:#0f1216;--card:#171b21;--card2:#1d222a;--line:#2a3038;--text:#e8ecf1;--dim:#8b95a3;
--gold:#d4a84a;--green:#43c08a;--red:#e0685e;--blue:#4a9ee0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:13px/1.5 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:18px}
h1{font-size:18px;margin:0;font-weight:700}
h1 b{color:var(--green)}
.sub{color:var(--dim);font-size:12px;margin-top:2px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.stat{background:var(--card2);border:1px solid var(--line);border-radius:10px;padding:12px}
.stat .k{color:var(--dim);font-size:12px}.stat .v{font-size:22px;font-weight:700;margin-top:4px}
.stat .v.gold{color:var(--gold)}.stat .v.green{color:var(--green)}.stat .v.red{color:var(--red)}
input,select,button{font:inherit;background:var(--card2);color:var(--text);border:1px solid var(--line);
border-radius:8px;padding:8px 10px;outline:none}
input:focus{border-color:var(--green)}
button{cursor:pointer;user-select:none}button:hover{border-color:var(--dim)}
.btn-main{background:var(--green);border-color:var(--green);color:#08110c;font-weight:700}
.btn-del{background:transparent;border-color:#5a3030;color:var(--red)}
.btn-sm{padding:4px 9px;font-size:12px;border-radius:6px}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.tab{padding:7px 14px;border-radius:8px;border:1px solid var(--line);background:var(--card);
color:var(--dim);cursor:pointer}.tab.on{color:var(--text);border-color:var(--green);background:#141a17}
table{width:100%;border-collapse:collapse}
th,td{padding:8px 6px;text-align:left;border-bottom:1px solid var(--line);vertical-align:middle}
th{color:var(--dim);font-weight:500;font-size:12px}
.badge{display:inline-block;padding:1px 8px;border-radius:9px;font-size:11px}
.badge.black{background:var(--gold);color:#15171b}
.badge.gold{border:1px solid #a6802e;color:var(--gold)}
.badge.normal{color:var(--dim)}
.tag{display:inline-block;padding:1px 7px;border-radius:6px;font-size:11px;background:#2a1414;color:var(--red)}
.mask{position:fixed;inset:0;background:#000000aa;display:flex;align-items:center;justify-content:center;padding:16px;z-index:9}
.modal{width:min(520px,100%);background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
.modal h3{margin:0 0 12px;font-size:15px}
.row{display:flex;gap:8px;align-items:center;margin-bottom:8px}
.row label{width:64px;color:var(--dim);font-size:12px;flex:none}
.row input,.row select{flex:1}
.foot{display:flex;justify-content:flex-end;gap:8px;margin-top:14px}
.muted{color:var(--dim)}.small{font-size:12px}
.pager{display:flex;justify-content:space-between;align-items:center;margin-top:10px;color:var(--dim);font-size:12px}
.hide{display:none}
.notice{background:#1a1f18;border:1px solid #3a4a30;border-radius:10px;padding:10px;margin-bottom:10px;color:#cfe0c0}
.warn{background:#241d17;border-color:#5a4526;color:#f0d9b0}
#login{max-width:360px;margin:12vh auto}
#login .card{text-align:center}
#login input{width:100%;margin:6px 0}
#login #uname{margin-top:10px}
.err{color:var(--red);font-size:12px;min-height:16px}
pre{white-space:pre-wrap;word-break:break-all;background:var(--card2);padding:10px;border-radius:8px;font-size:12px}
</style></head><body>
<div class="wrap">
 <div id="login" class="hide">
  <div class="card">
   <h1>GAMEPAD <b>STUDIO</b></h1>
   <div class="sub">管理后台 · 账号 + 密码</div>
   <input id="uname" placeholder="管理员账号" autocomplete="username">
   <input id="pw" type="password" placeholder="密码" autocomplete="current-password" onkeydown="if(event.key==='Enter')doLogin()">
   <div class="err" id="loginerr"></div>
   <button class="btn-main" style="width:100%" onclick="doLogin()">登录</button>
  </div>
 </div>

 <div id="app" class="hide">
  <div class="row" style="justify-content:space-between">
   <div><h1>GAMEPAD <b>STUDIO</b> 管理后台</h1><div class="sub" id="who"></div></div>
   <div class="row" style="margin:0">
    <button class="btn-sm" onclick="reloadAll()">刷新</button>
    <button class="btn-sm btn-del" onclick="doLogout()">退出</button>
   </div>
  </div>

  <div class="tabs">
   <div class="tab on" data-tab="overview">概览</div>
   <div class="tab" data-tab="users">用户</div>
   <div class="tab" data-tab="posts">帖子</div>
   <div class="tab" data-tab="comments">评论</div>
   <div class="tab" data-tab="notice">公告</div>
   <div class="tab" data-tab="logs">日志</div>
   <div class="tab" data-tab="tools">工具</div>
  </div>

  <div id="tab-overview">
   <div class="card"><div class="grid" id="stats"></div></div>
   <div class="card"><b>最近操作</b><div id="recent" class="small" style="margin-top:8px"></div></div>
   <div class="card"><b>最新注册</b><div id="newest" class="small" style="margin-top:8px"></div></div>
  </div>

  <div id="tab-users" class="hide">
   <div class="card">
    <div class="row"><input id="uq" placeholder="搜用户名 / UID / 称号" style="flex:1" onkeydown="if(event.key==='Enter')loadUsers(1)">
     <button onclick="loadUsers(1)">搜索</button></div>
    <div style="overflow:auto"><table><thead><tr><th>UID</th><th>用户名</th><th>徽标</th><th>称号</th>
    <th>帖子</th><th>评论</th><th>注册</th><th>操作</th></tr></thead><tbody id="utbody"></tbody></table></div>
    <div class="pager" id="upager"></div>
   </div>
  </div>

  <div id="tab-posts" class="hide">
   <div class="card">
    <div class="row"><input id="pq" placeholder="搜标题 / 正文 / 作者" style="flex:1" onkeydown="if(event.key==='Enter')loadPosts(1)">
     <button onclick="loadPosts(1)">搜索</button></div>
    <div style="overflow:auto"><table><thead><tr><th>#</th><th>标题</th><th>作者</th><th>赞/评</th><th>时间</th><th>操作</th></tr></thead>
    <tbody id="ptbody"></tbody></table></div>
    <div class="pager" id="ppager"></div>
   </div>
  </div>

  <div id="tab-comments" class="hide">
   <div class="card">
    <div style="overflow:auto"><table><thead><tr><th>#</th><th>所属帖子</th><th>作者</th><th>内容</th><th>时间</th><th>操作</th></tr></thead>
    <tbody id="ctbody"></tbody></table></div>
    <div class="pager" id="cpager"></div>
   </div>
  </div>

  <div id="tab-notice" class="hide">
   <div class="card">
    <b>发一条公告</b><div class="small muted">同时只生效一条；生效的公告会出现在客户端社区页和官网页顶（客户端下次更新后显示）</div>
    <div class="row" style="margin-top:10px"><input id="ntext" placeholder="公告内容，最多 200 字" style="flex:1">
     <select id="nlevel"><option value="info">普通</option><option value="warn">重要</option></select>
     <button class="btn-main" onclick="addNotice()">发布</button></div>
   </div>
   <div class="card"><b>历史公告</b><div id="nlist" style="margin-top:8px"></div></div>
  </div>

  <div id="tab-logs" class="hide">
   <div class="card">
    <div style="overflow:auto"><table><thead><tr><th>时间</th><th>动作</th><th>细节</th></tr></thead><tbody id="ltbody"></tbody></table></div>
    <div class="pager" id="lpager"></div>
   </div>
  </div>

  <div id="tab-tools" class="hide">
   <div class="card">
    <b>数据导出</b><div class="small muted">JSON 格式，下载后自己留档；数据库备份是热备份，不会打断服务</div>
    <div class="row" style="margin-top:10px">
     <button onclick="dl('/admin/api/export?kind=users')">导出用户</button>
     <button onclick="dl('/admin/api/export?kind=posts')">导出帖子</button>
     <button onclick="dl('/admin/api/export?kind=comments')">导出评论</button>
     <button class="btn-main" onclick="dl('/admin/api/backup')">下载数据库备份</button>
    </div>
   </div>
   <div class="card"><b>服务器配置</b><pre id="cfg"></pre></div>
  </div>
 </div>
</div>

<div class="mask hide" id="mask"><div class="modal" id="modal"></div></div>

<script>
const $=id=>document.getElementById(id);
let state={users:{page:1},posts:{page:1},comments:{page:1},logs:{page:1}};

async function api(path,opts){
  const res=await fetch(path,Object.assign({credentials:'same-origin'},opts||{}));
  if(res.status===401){showLogin();throw new Error('unauthorized');}
  const ct=res.headers.get('content-type')||'';
  const body=ct.includes('json')?await res.json():await res.text();
  if(!res.ok){
    const msg=(body&&body.detail)||(typeof body==='string'?body:'出错了');
    throw new Error(msg);
  }
  return body;
}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function showLogin(){$('login').classList.remove('hide');$('app').classList.add('hide')}
function showApp(){$('login').classList.add('hide');$('app').classList.remove('hide')}

async function doLogin(){
  $('loginerr').textContent='';
  try{
    await api('/admin/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({username:$('uname').value,password:$('pw').value})});
    showApp();reloadAll();
  }catch(e){$('loginerr').textContent=e.message}
}
async function doLogout(){try{await api('/admin/api/logout',{method:'POST'})}catch(e){}showLogin()}

document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===t));
  ['overview','users','posts','comments','notice','logs','tools'].forEach(k=>
    $('tab-'+k).classList.toggle('hide',k!==t.dataset.tab));
  if(t.dataset.tab==='users')loadUsers(state.users.page);
  if(t.dataset.tab==='posts')loadPosts(state.posts.page);
  if(t.dataset.tab==='comments')loadComments(state.comments.page);
  if(t.dataset.tab==='notice')loadNotices();
  if(t.dataset.tab==='logs')loadLogs(state.logs.page);
  if(t.dataset.tab==='tools')loadCfg();
});

function badgeChip(b){
  const t={black:'认证',gold:'靓号',normal:'普通'}[b]||b;
  return '<span class="badge '+esc(b)+'">'+esc(t)+'</span>';
}

async function loadOverview(){
  const d=await api('/admin/api/overview');
  $('who').textContent='服务器时间 '+d.server_time+'　·　管理员 UID 名单：'+(d.admin_uids||'（空）');
  const cards=[['用户',d.users,''],['今日新注册',d.today,'green'],['7 天新注册',d.week,''],
    ['帖子',d.posts,''],['评论',d.comments,''],['点赞',d.likes,''],
    ['认证',d.certified,'gold'],['靓号',d.gold,'gold'],['已封禁',d.banned,'red']];
  $('stats').innerHTML=cards.map(([k,v,c])=>`<div class="stat"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`).join('');
  $('recent').innerHTML=d.logs.length?d.logs.map(l=>`<div>${esc(l.ts)} · ${esc(l.action)} · <span class="muted">${esc(l.detail)}</span></div>`).join(''):'<span class="muted">还没有操作记录</span>';
  $('newest').innerHTML=d.newest.length?d.newest.map(u=>`<div>UID ${u.uid} · ${esc(u.username)} · <span class="muted">${esc(u.when)}</span></div>`).join(''):'<span class="muted">还没有用户</span>';
}

async function loadUsers(page){
  state.users.page=page;
  const d=await api('/admin/api/users?page='+page+'&q='+encodeURIComponent($('uq').value));
  $('utbody').innerHTML=d.items.map(u=>`<tr>
    <td>${u.uid}</td><td>${esc(u.username)}${u.banned?' <span class="tag">封禁</span>':''}</td>
    <td>${badgeChip(u.badge)}</td><td>${esc(u.title)||'<span class="muted">—</span>'}</td>
    <td>${u.posts}</td><td>${u.comments}</td><td class="small muted">${esc(u.created_at)}</td>
    <td><button class="btn-sm" onclick='editUser(${JSON.stringify(u)})'>编辑</button>
    <button class="btn-sm btn-del" onclick="delUser(${u.uid})">删除</button></td></tr>`).join('')
    ||'<tr><td colspan="8" class="muted">没找到用户</td></tr>';
  pager('upager',d,loadUsers);
}

function editUser(u){
  $('modal').innerHTML=`<h3>编辑 UID ${u.uid}</h3>
   <div class="row"><label>用户名</label><input id="e_name" value="${esc(u.username)}"></div>
   <div class="row"><label>称号</label><input id="e_title" value="${esc(u.title)}" maxlength="8" placeholder="最多 8 字"></div>
   <div class="row"><label>签名</label><input id="e_bio" value="${esc(u.bio)}" maxlength="40" placeholder="最多 40 字"></div>
   <div class="row"><label>配色</label><input id="e_color" value="${esc(u.color)}" placeholder="#D4A84A（留空＝默认灰）"></div>
   <div class="row"><label>徽标</label><select id="e_badge">
     <option value="">自动（按 UID 规则）</option>
     <option value="black">认证（金底深字）</option>
     <option value="gold">靓号（金边金字）</option></select></div>
   <div class="row"><label>封禁</label><select id="e_ban">
     <option value="0">正常</option><option value="1">禁止登录 / 发帖</option></select></div>
   <div class="row"><label>角色</label><select id="e_role">
     <option value="user">普通用户</option><option value="moderator">版主</option></select></div>
   <div class="err" id="e_err"></div>
   <div class="foot"><button onclick="closeModal()">取消</button>
    <button class="btn-main" onclick="saveUser(${u.uid})">保存</button></div>`;
  $('e_badge').value=u.badge_override||'';$('e_ban').value=u.banned?'1':'0';$('e_role').value=u.role;
  $('mask').classList.remove('hide');
}
function closeModal(){$('mask').classList.add('hide')}
async function saveUser(uid){
  const body={username:$('e_name').value,title:$('e_title').value,bio:$('e_bio').value,
    color:$('e_color').value,badge_override:$('e_badge').value,banned:$('e_ban').value==='1',
    role:$('e_role').value};
  try{await api('/admin/api/users/'+uid,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    closeModal();loadUsers(state.users.page);loadOverview();
  }catch(e){$('e_err').textContent=e.message}
}
async function delUser(uid){
  if(!confirm('删除 UID '+uid+' 以及他的帖子、评论、点赞？不可恢复。'))return;
  try{await api('/admin/api/users/'+uid,{method:'DELETE'});loadUsers(state.users.page);loadOverview();}
  catch(e){alert(e.message)}
}

async function loadPosts(page){
  state.posts.page=page;
  const d=await api('/admin/api/posts?page='+page+'&q='+encodeURIComponent($('pq').value));
  $('ptbody').innerHTML=d.items.map(p=>`<tr><td>${p.id}</td>
    <td>${esc(p.title)}<div class="small muted">${esc(p.content)}</div></td>
    <td>${esc(p.username)}<div class="small muted">UID ${p.uid}</div></td>
    <td>${p.likes}/${p.comments}</td><td class="small muted">${esc(p.created_at)}</td>
    <td><button class="btn-sm btn-del" onclick="delPost(${p.id})">删除</button></td></tr>`).join('')
    ||'<tr><td colspan="6" class="muted">没有帖子</td></tr>';
  pager('ppager',d,loadPosts);
}
async function delPost(id){
  if(!confirm('删除帖子 #'+id+'（连带评论和点赞）？'))return;
  try{await api('/admin/api/posts/'+id,{method:'DELETE'});loadPosts(state.posts.page);loadOverview();}catch(e){alert(e.message)}
}

async function loadComments(page){
  state.comments.page=page;
  const d=await api('/admin/api/comments?page='+page);
  $('ctbody').innerHTML=d.items.map(c=>`<tr><td>${c.id}</td>
    <td>${esc(c.post_title)}<div class="small muted">#${c.post_id}</div></td>
    <td>${esc(c.username)}<div class="small muted">UID ${c.uid}</div></td>
    <td>${esc(c.content)}</td><td class="small muted">${esc(c.created_at)}</td>
    <td><button class="btn-sm btn-del" onclick="delComment(${c.id})">删除</button></td></tr>`).join('')
    ||'<tr><td colspan="6" class="muted">没有评论</td></tr>';
  pager('cpager',d,loadComments);
}
async function delComment(id){
  if(!confirm('删除评论 #'+id+'？'))return;
  try{await api('/admin/api/comments/'+id,{method:'DELETE'});loadComments(state.comments.page);loadOverview();}catch(e){alert(e.message)}
}

async function loadNotices(){
  const d=await api('/admin/api/notices');
  $('nlist').innerHTML=d.items.length?d.items.map(n=>`<div class="row" style="margin:0;padding:6px 0;border-bottom:1px solid var(--line)">
    <span class="badge ${n.active?'black':'normal'}">${n.active?'生效中':'已停用'}</span>
    <span style="flex:1;margin-left:8px">${esc(n.text)}<span class="muted small"> · ${esc(n.created_at)}</span></span>
    <button class="btn-sm" onclick="toggleNotice(${n.id},${n.active?0:1})">${n.active?'停用':'启用'}</button>
    <button class="btn-sm btn-del" onclick="delNotice(${n.id})">删除</button></div>`).join('')
    :'<span class="muted">还没有公告</span>';
}
async function addNotice(){
  try{await api('/admin/api/notices',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text:$('ntext').value,level:$('nlevel').value})});
    $('ntext').value='';loadNotices();loadOverview();}catch(e){alert(e.message)}
}
async function toggleNotice(id,active){
  await api('/admin/api/notices/'+id+'/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({active})});
  loadNotices();loadOverview();
}
async function delNotice(id){
  if(!confirm('删除这条公告？'))return;
  await api('/admin/api/notices/'+id,{method:'DELETE'});loadNotices();loadOverview();
}

async function loadLogs(page){
  state.logs.page=page;
  const d=await api('/admin/api/logs?page='+page);
  $('ltbody').innerHTML=d.items.map(l=>`<tr><td class="small muted">${esc(l.ts)}</td><td>${esc(l.action)}</td>
    <td class="small">${esc(l.detail)}</td></tr>`).join('')||'<tr><td colspan="3" class="muted">没有日志</td></tr>';
  pager('lpager',d,loadLogs);
}

async function loadCfg(){
  const d=await api('/admin/api/overview');
  $('cfg').textContent='管理员 UID 名单：'+(d.admin_uids||'（空）')+'\n服务器时间：'+d.server_time
    +'\n用户 '+d.users+' · 帖子 '+d.posts+' · 评论 '+d.comments+' · 点赞 '+d.likes;
}
function pager(id,d,fn){
  const pages=Math.max(1,Math.ceil(d.total/(d.limit||30)));
  $(id).innerHTML=`<span>共 ${d.total} 条 · 第 ${d.page}/${pages} 页</span>
   <span><button class="btn-sm" ${d.page<=1?'disabled':''} onclick="(${fn.name})(state[${JSON.stringify(fn.name.replace('load','').toLowerCase())}||{page:1}).page-1)">上一页</button>
   <button class="btn-sm" ${d.page>=pages?'disabled':''} onclick="(${fn.name})((state[${JSON.stringify(fn.name.replace('load','').toLowerCase())}].page||1)+1)">下一页</button></span>`;
}
function dl(path){window.location.href=path}

function reloadAll(){
  loadOverview().catch(()=>{});
  const active=document.querySelector('.tab.on').dataset.tab;
  if(active==='users')loadUsers(state.users.page);
  if(active==='posts')loadPosts(state.posts.page);
  if(active==='comments')loadComments(state.comments.page);
  if(active==='notice')loadNotices();
  if(active==='logs')loadLogs(state.logs.page);
  if(active==='tools')loadCfg();
}
(async()=>{
  try{const w=await api('/admin/api/whoami'); w.admin?(showApp(),reloadAll()):showLogin();}catch(e){showLogin()}
})();
</script></body></html>
"""
