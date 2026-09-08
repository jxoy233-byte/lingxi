#!/usr/bin/env bash
# run.sh — lingxi-sync 的 cron 入口脚本
#
# 默认职责（极简）：
#   1) 自动创建 logs/ 目录（兜底 cron >> 的父目录不存在问题）
#   2) 调用 lingxi-sync.sh 并透传所有参数
#
# 日志清理策略（由 start.sh 在部署时根据系统能力决定）：
#   - 有 logrotate：交给 logrotate 处理，run.sh 不做清理
#   - 无 logrotate：start.sh 会注入 truncate 段到本文件末尾（见 TRUNCATE_MARKER）
#
# 不要手动加 truncate 段：start.sh 会动态管理它

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SYNC_SH="$SCRIPT_DIR/lingxi-sync.sh"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/lingxi-sync.log"

# ─────────── 1. 自动创建 logs/ 目录 ────────────
if [ ! -d "$LOG_DIR" ]; then
    mkdir -p "$LOG_DIR" || { echo "[run.sh] ❌ 创建日志目录失败: $LOG_DIR" >&2; exit 3; }
    chmod 755 "$LOG_DIR"
    echo "[run.sh] 已创建日志目录: $LOG_DIR"
fi

# ─────────── 2. 调用同步脚本 ────────────
if [ ! -x "$SYNC_SH" ]; then
    echo "[run.sh] ❌ 同步脚本不可执行: $SYNC_SH" >&2
    exit 3
fi

exec "$SYNC_SH" "$@"
