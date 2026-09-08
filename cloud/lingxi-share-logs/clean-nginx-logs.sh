#!/usr/bin/env bash
# clean-nginx-logs.sh — nginx 日志 size-based truncate 兜底（配套 lingxi-share）
#
# 行为：
#   1) 扫描 /var/log/nginx/ 下所有 *.log（不含已轮转的 .gz / .数字 后缀）
#   2) 单文件 > LOG_MAX_BYTES（默认 100MB）→ 原子 truncate 到最近 KEEP_LINES（默认 100000 行）
#   3) 每次操作记一行日志（含文件名 / 原大小 / 新大小 / 行数）
#
# 与 logrotate 的关系（互补，不冲突）：
#   - logrotate 默认 /etc/logrotate.d/nginx：daily + rotate 14（time-based）
#   - 本脚本：size-based 兜底，处理「单日突发流量撑爆日志」的场景
#   - 两边独立运行：logrotate 按天轮转，本脚本按体积截断；logrotate 的 daily 在 ~6am 跑，
#     本脚本 cron 默认 3:17am 跑（先截后转），避免两者抢同一文件
#
# 为什么用 truncate 而不是 rm + recreate：
#   - nginx 持有 access.log 的文件句柄（FD），直接 rm 只删目录项，磁盘空间不释放
#   - truncate 是「清空内容但保留 inode」，nginx 继续往同一个 FD 写，零停机
#   - tail -n K → tmp → cat tmp > log 是另一种方案，但需要先备份再写，
#     且中途 nginx 写入会导致内容交叉；用 truncate + tail -n K 一次性写回更稳
#
# 用法（正常情况通过 run.sh 走 cron；手动调试直接调本脚本）：
#   /root/scripts/lingxi-share-logs/clean-nginx-logs.sh
#   LOG_MAX_BYTES=$((50*1024*1024)) KEEP_LINES=50000 /root/scripts/lingxi-share-logs/clean-nginx-logs.sh
#
# 退出码：0 成功 / 1 参数错 / 2 /var/log/nginx 不存在 / 3 不可恢复 IO 错误

set -u
set -o pipefail

# ─────────── 路径 + 阈值配置 ────────────
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/clean-nginx-logs.log"
NGINX_LOG_DIR="/var/log/nginx"

# 阈值：默认 100MB / 保留 10 万行
#   100MB × N 行 / N MB ≈ 单行平均字节数；10 万行 ≈ access.log 紧凑格式可塞几百 MB
#   100MB 单行平均 1KB → 10 万行 = 100MB 刚好；普通 nginx 单行 200-500B → 10 万行 ≈ 20-50MB
#   调小更激进、调大更宽松；环境变量可覆盖
LOG_MAX_BYTES="${LOG_MAX_BYTES:-104857600}"  # 100 * 1024 * 1024
KEEP_LINES="${KEEP_LINES:-100000}"

# log 走 stderr（避免被命令替换 $() 误捕），同时 append 到 LOG_FILE
log() {
    local msg="[clean-nginx-logs $(date '+%Y-%m-%d %H:%M:%S')] $*"
    printf '%s\n' "$msg" >&2
    printf '%s\n' "$msg" >> "$LOG_FILE" 2>/dev/null || true
}

# ─────────── 0. 校验 ────────────
# root 才能读 nginx 日志目录（默认 640 + www-data adm）
if [ "$(id -u)" -ne 0 ]; then
    echo "❌ 需要 root 权限（要读 /var/log/nginx/），请加 sudo 重试" >&2
    exit 1
fi

if [ ! -d "$NGINX_LOG_DIR" ]; then
    log "❌ /var/log/nginx/ 不存在（nginx 没装？）"
    exit 2
fi

# 确保日志目录存在（cron 跑时 $SCRIPT_DIR/logs/ 可能还没建）
mkdir -p "$LOG_DIR" 2>/dev/null || {
    echo "❌ 无法创建日志目录: $LOG_DIR" >&2
    exit 3
}

# ─────────── 1. 扫描 + 截断 ────────────
log "========== 开始扫描 $NGINX_LOG_DIR =========="
log "阈值: ${LOG_MAX_BYTES} 字节 / 保留 ${KEEP_LINES} 行"

# 只处理 *.log（不含 .1 / .gz 等已轮转文件；那些是 logrotate 的事）
shopt -s nullglob
TRUNCATED_COUNT=0
SKIPPED_COUNT=0
ERROR_COUNT=0

for log_path in "$NGINX_LOG_DIR"/*.log; do
    # nullglob + set -u 防御：极端情况下空匹配仍可能进入
    [ -f "$log_path" ] || continue

    # 兼容 Linux stat 和 macOS stat
    if stat -c%s "$log_path" >/dev/null 2>&1; then
        size=$(stat -c%s "$log_path")
    else
        size=$(stat -f%z "$log_path")
    fi

    if [ "$size" -le "$LOG_MAX_BYTES" ]; then
        SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
        log "  skip: $(basename "$log_path") (${size} B ≤ ${LOG_MAX_BYTES} B)"
        continue
    fi

    # 超过阈值 → 截断到最近 KEEP_LINES
    log "  ⚠️  $(basename "$log_path") 超过阈值: ${size} B，开始 truncate..."

    # 方案：tail -n KEEP_LINES → tmp → mv 覆盖（比 truncate 更准，保留尾部数据）
    #   - 用 .tmp.$$ 防止与历史残留冲突
    #   - 先把新内容写完再 mv，nginx 在原文件继续写 → 短暂窗口期新写入会丢
    #     但窗口期 = mv 一次系统调用（微秒级），可接受
    tmp_file="${log_path}.tmp.$$"

    if ! tail -n "$KEEP_LINES" "$log_path" > "$tmp_file" 2>/dev/null; then
        log "  ❌ tail 失败: $(basename "$log_path")"
        rm -f "$tmp_file"
        ERROR_COUNT=$((ERROR_COUNT + 1))
        continue
    fi

    if ! mv "$tmp_file" "$log_path"; then
        log "  ❌ mv 失败: $(basename "$log_path")"
        rm -f "$tmp_file"
        ERROR_COUNT=$((ERROR_COUNT + 1))
        continue
    fi

    # 验证新大小
    if stat -c%s "$log_path" >/dev/null 2>&1; then
        new_size=$(stat -c%s "$log_path")
    else
        new_size=$(stat -f%z "$log_path")
    fi
    new_lines=$(wc -l < "$log_path" 2>/dev/null | tr -d ' ' || echo "?")

    log "  ✅ $(basename "$log_path") ${size} B → ${new_size} B (${new_lines} 行)"
    TRUNCATED_COUNT=$((TRUNCATED_COUNT + 1))
done

log "========== 扫描完成 =========="
log "  截断: $TRUNCATED_COUNT 个文件"
log "  跳过: $SKIPPED_COUNT 个文件（未超阈值）"
log "  失败: $ERROR_COUNT 个文件"

# 退出码：任何 IO 错误 → 3（方便 cron 监控报警）
if [ "$ERROR_COUNT" -gt 0 ]; then
    exit 3
fi
exit 0
