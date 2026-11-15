#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美国宏观数据看板 - 一键更新入口
用法：
  python3 scripts/update.py                 # 精准增量更新（默认）
  python3 scripts/update.py --full          # 全量更新
流程：抓取数据 → 计算指标 → 运行专题规则 → 渲染 HTML
"""
import os, sys, subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(BASE_DIR, "scripts")


def run(script, args=None):
    cmd = [sys.executable, os.path.join(SCRIPTS, script)] + (args or [])
    print(f"\n>>> 执行 {script} {' '.join(args or [])}")
    r = subprocess.run(cmd, cwd=BASE_DIR)
    if r.returncode != 0:
        print(f"!!! {script} 执行失败，退出码 {r.returncode}")
        sys.exit(r.returncode)


if __name__ == "__main__":
    full = "--full" in sys.argv
    run("fetch_all.py", [] if full else ["--incremental"])
    run("analyze.py")
    run("render.py")
    print("\n✅ 看板更新完成")
