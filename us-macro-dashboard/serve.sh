#!/usr/bin/env bash
# 美国宏观数据看板 - 本机静态服务启动脚本
# 用法：bash serve.sh [端口]（默认 43187，高位端口避免与常用端口冲突）
# 说明：启动一个轻量静态服务托管 site/ 目录，供本地预览；
#       后续可配合 cloudflared 隧道把该端口暴露到外网域名。

PORT="${1:-43187}"
DIR="$(cd "$(dirname "$0")" && pwd)/site"

if [ ! -d "$DIR" ]; then
  echo "错误：未找到 $DIR ，请先运行 python3 scripts/update.py 生成站点。"
  exit 1
fi

echo "美国宏观数据看板 · 本机服务"
echo " 站点目录: $DIR"
echo " 访问地址: http://127.0.0.1:$PORT"
echo " 按 Ctrl+C 停止服务"
echo ""

cd "$DIR" && python3 -m http.server "$PORT" --bind 127.0.0.1
