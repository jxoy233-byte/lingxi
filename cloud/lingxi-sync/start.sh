#!/usr/bin/env bash
# start.sh — 一键启动 lingxi-sync 定时同步
#
# 行为：
#   1) 校验 root + crontab + git
#   2) 校验源目录脚本齐全
#   3) 把 lingxi-sync.sh / run.sh 复制到 /root/scripts/lingxi-sync/
#   4) 自动创建 logs/ 目录
#   5) 加执行权限
#   6) 部署日志清理策略：logrotate 优先；找不到时降级到脚本自清理
#   7) 注册 cron（每 30 分钟，幂等：精确匹配整行）
#   8) 立即触发一次同步（可选）
#
# 用法：
#   sudo ./start.sh           # 部署 + 立即跑一次
#   sudo ./start.sh --no-run  # 仅部署不跑

set -u
set -o pipefail

# ─────────── 0. 参数 + 环境校验 ────────────
SOURCE_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
INSTALL_DIR="/root/scripts/lingxi-sync"
DO_RUN=true
[ "${1:-}" = "--no-run" ] && DO_RUN=false

if [ "$(id -u)" -ne 0 ]; then
    echo "❌ 需要 root 权限（crontab + 写入 /root/），请加 sudo 重试" >&2
    exit 1
fi

if ! command -v crontab >/dev/null 2>&1; then
    echo "❌ crontab 命令不存在，请先装 cron: apt-get install -y cron" >&2
    exit 1
fi

if ! command -v git >/dev/null 2>&1; then
    echo "❌ git 命令不存在，请先装: apt-get install -y git" >&2
    exit 1
fi

for f in lingxi-sync.sh run.sh; do
    if [ ! -f "$SOURCE_DIR/$f" ]; then
        echo "❌ 源目录缺少脚本: $SOURCE_DIR/$f" >&2
        exit 1
    fi
done

echo "=== lingxi-sync 一键启动 ==="
echo "源目录: $SOURCE_DIR"
echo "目标目录: $INSTALL_DIR"

# ─────────── 1. 复制脚本 ────────────
if [ "$SOURCE_DIR" != "$INSTALL_DIR" ]; then
    echo "→ 复制脚本到 $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    cp "$SOURCE_DIR/lingxi-sync.sh" "$INSTALL_DIR/" || { echo "❌ 复制 lingxi-sync.sh 失败" >&2; exit 1; }
    cp "$SOURCE_DIR/run.sh" "$INSTALL_DIR/" || { echo "❌ 复制 run.sh 失败" >&2; exit 1; }
fi

# ─────────── 2. 创建 logs/ 目录 ────────────
mkdir -p "$INSTALL_DIR/logs"
chmod 755 "$INSTALL_DIR/logs"

# ─────────── 3. 加执行权限 ────────────
chmod +x "$INSTALL_DIR/lingxi-sync.sh" "$INSTALL_DIR/run.sh"

# ─────────── 3.5 部署日志清理策略 ────────────
# 策略优先级：logrotate（系统服务）> run.sh 自清理（兜底）
# 切换策略时同步修改 run.sh（deploy 时跑一次就行）

# 默认 run.sh 是「纯入口（不带 truncate）」；只有检测到无 logrotate 时才注入 truncate 段
TRUNCATE_MARKER="# ── self-clean truncate (no logrotate on this system) ──"

# 检测 logrotate
LOGROTATE_FILE="/etc/logrotate.d/lingxi-sync"
HAS_LOGROTATE=false
if command -v logrotate >/dev/null 2>&1; then
    HAS_LOGROTATE=true
fi

# 部署 / 更新 logrotate 配置
if $HAS_LOGROTATE; then
    LOGROTATE_CONF="${INSTALL_DIR}/logs/lingxi-sync.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    create 0644 root root
}"
    if [ -f "$LOGROTATE_FILE" ] && grep -q "${INSTALL_DIR}/logs/lingxi-sync.log" "$LOGROTATE_FILE"; then
        echo "→ logrotate 配置已存在，跳过"
    else
        if echo "$LOGROTATE_CONF" | tee "$LOGROTATE_FILE" >/dev/null; then
            if logrotate -d "$LOGROTATE_FILE" >/dev/null 2>&1; then
                echo "→ 已部署 logrotate 配置: $LOGROTATE_FILE"
            else
                echo "⚠️ logrotate 配置语法有问题，请手动检查: $LOGROTATE_FILE" >&2
            fi
        else
            echo "⚠️ 写入 logrotate 配置失败，请手动: sudo tee $LOGROTATE_FILE" >&2
            HAS_LOGROTATE=false  # 降级
        fi
    fi
else
    echo "→ 未检测到 logrotate 命令，将降级到 run.sh 自清理日志"
fi

# 根据 logrotate 状态决定 run.sh 内容
if ! $HAS_LOGROTATE; then
    # 注入 truncate 段到 run.sh（幂等：先剥掉旧段再追加）
    # 用 sed 删除旧 marker 后的所有内容到 EOF，重新追加新段
    TMP_RUN=$(mktemp)
    # 删掉从 marker 行开始到文件末尾的所有内容（marker 不存在则 no-op）
    if grep -qF "$TRUNCATE_MARKER" "$INSTALL_DIR/run.sh"; then
        # 删 marker 及其后所有行
        sed "/$TRUNCATE_MARKER/,\$d" "$INSTALL_DIR/run.sh" > "$TMP_RUN"
    else
        cp "$INSTALL_DIR/run.sh" "$TMP_RUN"
    fi
    # 追加 truncate 段
    cat >> "$TMP_RUN" <<'TRUNCATE_EOF'

# ── self-clean truncate (no logrotate on this system) ──
# 系统无 logrotate 时 run.sh 兜底：日志 > 10MB 时原子 truncate 到最近 5000 行
LOG_MAX_BYTES=$((10 * 1024 * 1024))
LOG_KEEP_LINES=5000
LOG_FILE="$LOG_DIR/lingxi-sync.log"

if [ -f "$LOG_FILE" ]; then
    LOG_SIZE=$(stat -c%s "$LOG_FILE" 2>/dev/null || stat -f%z "$LOG_FILE" 2>/dev/null || echo 0)
    if [ "$LOG_SIZE" -gt "$LOG_MAX_BYTES" ]; then
        TMP_LOG="${LOG_FILE}.tmp.$$"
        tail -n "$LOG_KEEP_LINES" "$LOG_FILE" > "$TMP_LOG" 2>/dev/null && mv "$TMP_LOG" "$LOG_FILE"
        echo "[run.sh] 日志超过 ${LOG_MAX_BYTES} 字节，已 truncate 到最近 ${LOG_KEEP_LINES} 行"
    fi
fi
TRUNCATE_EOF
    mv "$TMP_RUN" "$INSTALL_DIR/run.sh"
    chmod +x "$INSTALL_DIR/run.sh"
    echo "→ run.sh 已注入自清理 truncate 段"
else
    # 有 logrotate → 剥掉 run.sh 里的 truncate 段（保持纯净）
    if grep -qF "$TRUNCATE_MARKER" "$INSTALL_DIR/run.sh"; then
        TMP_RUN=$(mktemp)
        sed "/$TRUNCATE_MARKER/,\$d" "$INSTALL_DIR/run.sh" > "$TMP_RUN"
        mv "$TMP_RUN" "$INSTALL_DIR/run.sh"
        echo "→ run.sh 已移除自清理段（交给 logrotate）"
    fi
fi

# ─────────── 4. 注册 cron（精确匹配整行，幂等）───────────
CRON_LINE="*/30 * * * * $INSTALL_DIR/run.sh >> $INSTALL_DIR/logs/lingxi-sync.log 2>&1"
TMP_CRON=$(mktemp)
TMP_CRON_NEW=$(mktemp)
trap "rm -f '$TMP_CRON' '$TMP_CRON_NEW'" EXIT

crontab -l > "$TMP_CRON" 2>/dev/null || true

if grep -qxF "$CRON_LINE" "$TMP_CRON" 2>/dev/null; then
    echo "→ cron 已注册过完整行，跳过"
else
    if grep -qF "$INSTALL_DIR/run.sh" "$TMP_CRON" 2>/dev/null; then
        echo "⚠️ 检测到指向 $INSTALL_DIR/run.sh 的旧 cron 行（格式不同），先移除再追加新行"
        grep -vF "$INSTALL_DIR/run.sh" "$TMP_CRON" > "$TMP_CRON_NEW" || true
    else
        cp "$TMP_CRON" "$TMP_CRON_NEW"
    fi
    echo "$CRON_LINE" >> "$TMP_CRON_NEW"
    crontab "$TMP_CRON_NEW" || { echo "❌ crontab 写入失败" >&2; exit 1; }
    echo "→ 已注册 cron: $CRON_LINE"
fi

echo ""
echo "=== 启动完成 ==="
echo "脚本: $INSTALL_DIR/lingxi-sync.sh"
echo "入口: $INSTALL_DIR/run.sh"
echo "日志: $INSTALL_DIR/logs/lingxi-sync.log"
if $HAS_LOGROTATE; then
    echo "日志清理: logrotate ($LOGROTATE_FILE)"
else
    echo "日志清理: run.sh 自清理（10MB truncate 到 5000 行）"
fi
echo ""

# ─────────── 5. 立即触发一次 ────────────
if $DO_RUN; then
    echo "=== 立即触发一次同步 ==="
    "$INSTALL_DIR/run.sh"
    echo "=== 同步退出码: $? ==="
fi

echo ""
echo "查看状态:"
echo "  crontab -l | grep lingxi-sync    # 查看 cron"
echo "  tail -20 $INSTALL_DIR/logs/lingxi-sync.log  # 查看日志"
if $HAS_LOGROTATE; then
    echo "  logrotate -d $LOGROTATE_FILE   # 验证 logrotate 配置"
fi
echo ""
echo "停止定时: stop.sh"
