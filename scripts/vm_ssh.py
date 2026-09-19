"""
背备不悲 · Linux 虚拟机 SSH 执行工具

用途：宿主机（Windows）上没有 mysql 客户端，通过 SSH 到虚拟机里执行
     docker exec / 查配置 / 跑 SQL 等操作。

用法：
    # 直接给命令
    python scripts/vm_ssh.py "docker ps"

    # 执行一个本地 bash 脚本（推荐，避免 Windows 下的引号地狱）
    python scripts/vm_ssh.py -f scripts/_remote_probe.sh

    # 从标准输入读
    echo "ls -la /root" | python scripts/vm_ssh.py
"""

from __future__ import annotations

import argparse
import base64
import os
import sys

import paramiko

HOST = os.environ.get("VM_HOST", "192.168.1.100")
PORT = int(os.environ.get("VM_PORT", "22"))
USER = os.environ.get("VM_USER", "root")
PASSWORD = os.environ.get("VM_PASSWORD", "")


def run(body: str, timeout: int = 180) -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            HOST, port=PORT, username=USER, password=PASSWORD,
            timeout=15, banner_timeout=25, auth_timeout=25,
            look_for_keys=False, allow_agent=False,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"✗ SSH 连接失败 {USER}@{HOST}:{PORT} -> {type(exc).__name__}: {exc}")
        return 2

    # base64 传输，彻底避开 Windows/pwsh/bash 三层引号转义问题
    payload = base64.b64encode(body.encode("utf-8")).decode("ascii")
    command = f"echo {payload} | base64 -d | bash"

    try:
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
    finally:
        client.close()

    if out:
        print(out, end="" if out.endswith("\n") else "\n")
    if err.strip():
        print("--- stderr ---")
        print(err, end="" if err.endswith("\n") else "\n")
    print(f"[exit code: {code}]")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="在 Linux 虚拟机上执行 shell 命令")
    parser.add_argument("cmd", nargs="?", help="要执行的 shell 命令")
    parser.add_argument("-f", "--file", help="要执行的本地 bash 脚本文件")
    parser.add_argument("--timeout", type=int, default=180, help="超时秒数")
    args = parser.parse_args()

    if args.file:
        with open(args.file, encoding="utf-8") as fp:
            body = fp.read()
    elif args.cmd:
        body = args.cmd
    else:
        body = sys.stdin.read()

    if not body.strip():
        parser.print_help()
        return 1

    return run(body, timeout=args.timeout)


if __name__ == "__main__":
    sys.exit(main())
