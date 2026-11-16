"""用 paramiko 直连 ECS，把社区后端部署成 systemd 服务（80 端口）."""
import os
import sys
import time

import paramiko

HOST = os.environ.get("ECS_HOST", "8.217.155.133")
USER = os.environ.get("ECS_USER", "root")
PW = os.environ.get("ECS_PW", "")
LOCAL = "/home/user/gscomm"
REMOTE = "/opt/gamepad-community"

UNIT = """[Unit]
Description=Gamepad Studio Community
After=network.target

[Service]
User=root
WorkingDirectory={remote}
Environment=GS_COMMUNITY_DB={remote}/data/community.db
Environment=GS_ADMIN_UIDS=
ExecStart={remote}/venv/bin/uvicorn app:app --host 0.0.0.0 --port 80
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def run(cli, cmd, quiet=False):
    stdin, stdout, stderr = cli.exec_command(cmd, timeout=600)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if not quiet:
        if out.strip():
            print(out.strip()[-1500:])
        if err.strip():
            print("[stderr]", err.strip()[-800:])
        print(f"[cmd exit={code}] {cmd[:80]}")
    return code, out, err


def main():
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, username=USER, password=PW, timeout=25, banner_timeout=30, auth_timeout=30)
    print("[ok] ssh connected")

    run(cli, "cat /etc/os-release | head -3")
    run(cli, "uname -m; python3 -V")
    run(cli, "apt-get update -qq || dnf -y makecache", quiet=True)
    run(cli, "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip || "
             "dnf install -y python3-pip", quiet=True)
    run(cli, "python3 -V; python3 -m venv --help >/dev/null 2>&1 && echo venv_ok")

    run(cli, f"mkdir -p {REMOTE}/data")
    sftp = cli.open_sftp()
    for name in ("app.py", "requirements.txt"):
        sftp.put(os.path.join(LOCAL, name), f"{REMOTE}/{name}")
        print(f"[upload] {name}")
    with sftp.open(f"{REMOTE}/gamepad-community.service", "w") as fh:
        fh.write(UNIT.format(remote=REMOTE))
    sftp.close()

    run(cli, f"cd {REMOTE} && python3 -m venv venv && "
             f"./venv/bin/pip install -q -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt",
        quiet=True)
    run(cli, f"{REMOTE}/venv/bin/python -c 'import fastapi,uvicorn;print(\"deps\",fastapi.__version__)'")

    run(cli, f"cp {REMOTE}/gamepad-community.service /etc/systemd/system/ && "
             "systemctl daemon-reload && systemctl enable --now gamepad-community")
    time.sleep(3)
    run(cli, "systemctl is-active gamepad-community; ss -lntp | grep ':80 ' || true")
    run(cli, "curl -s -m 5 http://127.0.0.1/api/health || echo LOCAL_CURL_FAILED")
    run(cli, "journalctl -u gamepad-community -n 15 --no-pager || true")
    cli.close()
    print("[done]")


if __name__ == "__main__":
    main()
