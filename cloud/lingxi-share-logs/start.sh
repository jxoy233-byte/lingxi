#!/usr/bin/env bash
# start.sh — 一键部署 nginx 日志清理定时任务
#
# 行为：
#   1) 校验 root + crontab
#   2) 校验源目录脚本齐全
#   3) 把 clean-nginx-logs.sh / run.sh 复制到 /root/scripts/lingxi-share-logs/
#   4) 自动创建 logs/ 目录
#   5) 加执行权限
#   6) 注册 cron（每天凌晨 3:17，幂等：精确匹配整行）
#   7) 立即触发一次（可选）
#
# 用法：
#   sudo ./start.sh           # 部署 + 立即跑一次
#   sudo ./start.sh --no-run  # 仅部署不跑

set -u
set -o pipefail

# ─────────── 0. 参数 + 环境校验 ────────────
SOURCE_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
INSTALL_DIR="/root/scripts/lingxi-share-logs"
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

for f in clean-nginx-logs.sh run.sh; do
    if [ ! -f "$SOURCE_DIR/$f" ]; then
        echo "❌ 源目录缺少脚本: $SOURCE_DIR/$f" >&2
        exit 1
    fi
done

echo "=== lingxi-share-logs 一键启动 ==="
echo "源目录: $SOURCE_DIR"
echo "目标目录: $INSTALL_DIR"

# ─────────── 1. 复制脚本 ────────────
if [ "$SOURCE_DIR" != "$INSTALL_DIR" ]; then
    echo "→ 复制脚本到 $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    cp "$SOURCE_DIR/clean-nginx-logs.sh" "$INSTALL_DIR/" || { echo "❌ 复制 clean-nginx-logs.sh 失败" >&2; exit 1; }
    cp "$SOURCE_DIR/run.sh" "$INSTALL_DIR/" || { echo "❌ 复制 run.sh 失败" >&2; exit 1; }
fi

# ─────────── 2. 创建 logs/ 目录 ────────────
mkdir -p "$INSTALL_DIR/logs"
chmod 755 "$INSTALL_DIR/logs"

# ─────────── 3. 加执行权限 ────────────
chmod +x "$INSTALL_DIR/clean-nginx-logs.sh" "$INSTALL_DIR/run.sh"

# ─────────── 4. 注册 cron（精确匹配整行，幂等）───────────
# 3:17am 跑：避开 :00 / :30 整点（多机器集中 cron 抢资源）+ 早于默认 logrotate 6:25am
CRON_LINE="17 3 * * * $INSTALL_DIR/run.sh >> $INSTALL_DIR/logs/clean-nginx-logs.log 2>&1"
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
echo "脚本: $INSTALL_DIR/clean-nginx-logs.sh"
echo "入口: $INSTALL_DIR/run.sh"
echo "日志: $INSTALL_DIR/logs/clean-nginx-logs.log"
echo "触发: 每天 3:17am（清理 /var/log/nginx/*.log 超过 100MB 的）"
echo ""

# ─────────── 5. 立即触发一次 ────────────
if $DO_RUN; then
    echo "=== 立即触发一次扫描 ==="
    "$INSTALL_DIR/run.sh"
    echo "=== 扫描退出码: $? ==="
fi

echo ""
echo "查看状态:"
echo "  crontab -l | grep lingxi-share-logs    # 查看 cron"
echo "  tail -20 $INSTALL_DIR/logs/clean-nginx-logs.log  # 查看清理日志"
echo "  ls -lh /var/log/nginx/                # 看当前日志大小"
echo ""
echo "停止定时: stop.sh"
