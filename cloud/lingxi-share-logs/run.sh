#!/usr/bin/env bash
# run.sh — lingxi-share-logs 的 cron 入口脚本
#
# 默认职责（极简）：
#   1) 自动创建 logs/ 目录（兜底 cron >> 的父目录不存在问题）
#   2) 调用 clean-nginx-logs.sh 并透传所有参数
#
# 日志清理策略（由本脚本 + clean-nginx-logs.sh 组合实现，外部系统不参与）：
#   - size-based truncate：本脚本调 clean-nginx-logs.sh 跑
#   - time-based rotation：交给系统 /etc/logrotate.d/nginx 默认配置（daily + rotate 14）
#   - 两层互补：单日突发流量 → 本脚本截断；日积月累 → logrotate 轮转

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
CLEAN_SH="$SCRIPT_DIR/clean-nginx-logs.sh"
LOG_DIR="$SCRIPT_DIR/logs"

# ─────────── 1. 自动创建 logs/ 目录 ────────────
if [ ! -d "$LOG_DIR" ]; then
    mkdir -p "$LOG_DIR" || { echo "[run.sh] ❌ 创建日志目录失败: $LOG_DIR" >&2; exit 3; }
    chmod 755 "$LOG_DIR"
    echo "[run.sh] 已创建日志目录: $LOG_DIR"
fi

# ─────────── 2. 调用清理脚本 ────────────
if [ ! -x "$CLEAN_SH" ]; then
    echo "[run.sh] ❌ 清理脚本不可执行: $CLEAN_SH" >&2
    exit 3
fi

exec "$CLEAN_SH" "$@"
