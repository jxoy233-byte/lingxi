#!/usr/bin/env bash
# stop.sh — 一键停止 lingxi-share-logs 定时任务
#
# 行为：
#   1) 从 crontab 移除 lingxi-share-logs 相关行（保留其他 cron 任务不动）
#   2) 可选 --purge 删除部署目录（必须 --yes/-y 显式确认）
#
# 关键安全保证：
#   - 过滤后 crontab 不为空才写入（避免误清空用户所有 cron）
#   - --purge 不带 --yes 直接拒绝（不弹 read，CI/脚本场景友好）
#
# 用法：
#   sudo ./stop.sh                # 仅移除 cron，保留脚本
#   sudo ./stop.sh --purge --yes  # 移除 cron + 删除 /root/scripts/lingxi-share-logs/
#   sudo ./stop.sh --purge -y     # 同上（短选项）

set -u
set -o pipefail

INSTALL_DIR="/root/scripts/lingxi-share-logs"
DO_PURGE=false
SKIP_CONFIRM=false
for arg in "$@"; do
    case "$arg" in
        --purge) DO_PURGE=true ;;
        --yes|-y) SKIP_CONFIRM=true ;;
        -h|--help)
            echo "用法: sudo $0 [--purge] [--yes|-y]"
            echo ""
            echo "选项:"
            echo "  --purge    删除整个部署目录（必须 --yes 确认）"
            echo "  --yes|-y   跳过确认（脚本化场景）"
            exit 0
            ;;
        *)
            echo "❌ 未知参数: $arg" >&2
            echo "运行 $0 --help 查看用法" >&2
            exit 1
            ;;
    esac
done

# root 校验（仅当 --purge 时需要；只移 cron 用 sudo 跑也行）
if $DO_PURGE && [ "$(id -u)" -ne 0 ]; then
    echo "❌ --purge 需要 root 权限（删除 /root/scripts/lingxi-share-logs/），请加 sudo 重试" >&2
    exit 1
fi

# --purge 必须显式 --yes（防止误删 —— 拒绝 read 交互式询问）
if $DO_PURGE && ! $SKIP_CONFIRM; then
    echo "❌ --purge 必须配合 --yes/-y 显式确认（防止误删）" >&2
    echo "   例: sudo $0 --purge --yes" >&2
    exit 1
fi

echo "=== lingxi-share-logs 停止 ==="

# ─────────── 1. 从 crontab 移除 lingxi-share-logs 行 ────────────
TMP_CRON=$(mktemp)
TMP_CRON_NEW=$(mktemp)
trap "rm -f '$TMP_CRON' '$TMP_CRON_NEW'" EXIT

crontab -l > "$TMP_CRON" 2>/dev/null || true

if grep -qF "$INSTALL_DIR/run.sh" "$TMP_CRON" 2>/dev/null; then
    # 过滤掉包含 lingxi-share-logs 路径的行（保留其他 cron）
    grep -vF "$INSTALL_DIR/run.sh" "$TMP_CRON" > "$TMP_CRON_NEW" || true

    # ⚠️ 安全兜底：过滤后 crontab 不能为空，否则会清空用户所有 cron
    if [ ! -s "$TMP_CRON_NEW" ]; then
        echo "⚠️ 检测到过滤后 crontab 为空（lingxi-share-logs 是你唯一的 cron）" >&2
        echo "⚠️ 为防止误删其他潜在配置，本次保留 crontab 原状" >&2
        echo "⚠️ 如确认要清空全部 cron，请手动执行: crontab -r" >&2
    else
        crontab "$TMP_CRON_NEW" || { echo "❌ crontab 写入失败" >&2; exit 1; }
        echo "→ 已从 crontab 移除 lingxi-share-logs 行"
    fi
else
    echo "→ crontab 里没找到 lingxi-share-logs 任务，无需移除"
fi

# ─────────── 2. 处理 --purge ────────────
if $DO_PURGE; then
    if [ ! -d "$INSTALL_DIR" ]; then
        echo "→ $INSTALL_DIR 已不存在，跳过删除"
    else
        rm -rf "$INSTALL_DIR"
        echo "→ 已删除 $INSTALL_DIR（所有脚本 + 日志）"
    fi
fi

echo ""
echo "=== 停止完成 ==="
echo "恢复定时: start.sh"
