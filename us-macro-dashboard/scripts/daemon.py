#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""美国宏观数据看板 · 本地静态服务守护进程

目的：让 http://127.0.0.1:43187 长期可用，不再因为终端关掉/电脑重启而打不开。

机制：
- 由 Windows 计划任务在登录时启动，用 pythonw.exe 无窗口运行
- 监控 43187 端口，静态服务进程退出/崩溃后自动重新拉起
- 用独立锁端口 43188 保证单实例，计划任务看门狗重复触发时直接静默退出

只用 Python 标准库，不安装任何包，不影响任何 Python 环境。

手动启动：pythonw scripts/daemon.py
手动停止：taskkill /F /IM pythonw.exe（或从任务管理器结束）
日志：logs/serve.log
"""

import os
import socket
import subprocess
import sys
import time
from datetime import datetime

HOST = "127.0.0.1"
PORT = 43187
LOCK_PORT = 43188          # 仅用于单实例互斥，不对外提供 HTTP
CHECK_INTERVAL = 15        # 监控间隔（秒）
STARTUP_GRACE = 3          # 拉起后等待就绪的时间（秒）

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(BASE, "site")
LOG_DIR = os.path.join(BASE, "logs")
LOG_FILE = os.path.join(LOG_DIR, "serve.log")
LOG_MAX = 2 * 1024 * 1024  # 2MB 滚动


def log(msg):
    line = "[%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        if not os.path.isdir(LOG_DIR):
            os.makedirs(LOG_DIR)
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > LOG_MAX:
            try:
                os.replace(LOG_FILE, LOG_FILE + ".1")
            except OSError:
                pass
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def port_listening(port, host=HOST):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def acquire_lock():
    """绑定锁端口实现单实例。成功返回 socket（须持有引用），失败返回 None。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name != "nt":
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((HOST, LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


def spawn_server():
    """启动静态服务子进程。"""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "--bind", HOST],
        cwd=SITE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )


def main():
    lock = acquire_lock()
    if lock is None:
        # 已有实例在跑，静默退出（看门狗重复触发时走这里）
        return 0

    if not os.path.isdir(SITE):
        log("错误：站点目录不存在 %s" % SITE)
        return 1

    log("守护进程启动 pid=%d，监控 %s:%d" % (os.getpid(), HOST, PORT))

    child = None
    fails = 0

    while True:
        try:
            if port_listening(PORT):
                # 端口正常。若子进程已退出，说明是别的进程在服务，清理引用即可
                if child is not None and child.poll() is not None:
                    log("静态服务进程退出 code=%s（端口已被其他进程接管）" % child.returncode)
                    child = None
                fails = 0
            elif child is not None and child.poll() is None:
                # 子进程活着但端口未监听，可能仍在启动，继续等
                pass
            else:
                if child is not None:
                    log("静态服务进程退出 code=%s，准备重启" % child.returncode)
                    child = None
                child = spawn_server()
                log("拉起静态服务 pid=%d" % child.pid)
                time.sleep(STARTUP_GRACE)
                if port_listening(PORT):
                    log("静态服务已就绪")
                    fails = 0
                else:
                    fails += 1
                    log("拉起后未监听（连续第 %d 次）" % fails)
                    if fails >= 5:
                        log("连续失败过多，退避 60 秒")
                        time.sleep(60)
                        fails = 0
        except Exception as e:
            log("监控循环异常: %r" % e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    sys.exit(main() or 0)
