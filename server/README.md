# Gamepad Studio 社区后端

FastAPI + SQLite 的轻量社区服务，给客户端「社区」页用。单文件 `app.py`，不依赖外部数据库。

## 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查，返回服务名与注册/帖子数 |
| POST | `/api/register` | 注册，JSON `{username, password}`，返回 token + user |
| POST | `/api/login` | 登录，同上 |
| GET | `/api/me` | 当前账号（需 `Authorization: Bearer <token>`） |
| GET | `/api/profile/{uid}` | 查某个 UID 的资料 |
| GET | `/api/posts?limit=&offset=&kind=` | 帖子列表 |
| POST | `/api/posts` | 发帖 `{title, content, kind}` |
| GET | `/api/posts/{id}` | 帖子详情 |
| POST | `/api/posts/{id}/comments` | 回帖 `{content}` |
| POST | `/api/posts/{id}/like` | 点赞 / 取消点赞 |
| GET | `/api/stats` | 用户数、帖子数、评论数 |

`/` 是深色静态首页，`/docs` 是自动生成的接口文档。

## UID 与徽标规则

UID 从 1001 起自增，注册顺序决定。徽标由 `badge_for()` 计算：

- **black（认证）**：`role=admin`，或 UID 出现在环境变量 `GS_ADMIN_UIDS` 里（逗号分隔，例如 `GS_ADMIN_UIDS=1001,1002`）
- **gold（靓号）**：3 位以内、豹子号（8888）、连号（1234 / 5678）、整千整万（1000 / 10000）、双对号（1122）
- **normal**：其余

## 部署

### 方式一：一键部署（推荐）

需要一台能 SSH 的 Linux 服务器（Ubuntu 22.04 实测）：

```bash
pip install paramiko
ECS_HOST=<服务器IP> ECS_USER=root ECS_PW=<密码> python3 deploy.py
```

脚本会：装 `python3-venv` → 建 `/opt/gamepad-community` → 上传代码 → 建 venv 并从阿里云镜像装依赖 →
写 systemd 单元并 `enable --now` → 健康检查。幂等，可重复执行。

### 方式二：手动部署

```bash
sudo mkdir -p /opt/gamepad-community/data
sudo cp app.py requirements.txt /opt/gamepad-community/
cd /opt/gamepad-community
python3 -m venv venv
./venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
sudo cp gamepad-community.service /etc/systemd/system/   # deploy.py 里会生成，或按下面的内容自建
sudo systemctl daemon-reload && sudo systemctl enable --now gamepad-community
```

systemd 单元（`/etc/systemd/system/gamepad-community.service`）：

```ini
[Unit]
Description=Gamepad Studio Community
After=network.target

[Service]
User=root
WorkingDirectory=/opt/gamepad-community
Environment=GS_COMMUNITY_DB=/opt/gamepad-community/data/community.db
Environment=GS_ADMIN_UIDS=
ExecStart=/opt/gamepad-community/venv/bin/uvicorn app:app --host 0.0.0.0 --port 80
Restart=always

[Install]
WantedBy=multi-user.target
```

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `GS_COMMUNITY_DB` | `./community.db` | SQLite 路径 |
| `GS_ADMIN_UIDS` | 空 | 逗号分隔的 UID，命中即判为 `black` 认证 |

## 安全说明

- 密码用 PBKDF2-HMAC-SHA256（随机盐）存哈希，不存明文
- 登录换取 Bearer token（有效期 30 天），客户端只落盘 token
- 目前默认跑 HTTP，密码在网络上明文传输；有域名后建议加 Let's Encrypt 证书改走 443
- 数据只有 `community.db` 一个文件，备份直接拷它（建议停服务后拷，或用 `sqlite3 ... ".backup"`）
