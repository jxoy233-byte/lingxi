#!/usr/bin/env bash
# uninstall.sh — 一键卸载 lingxi-share（nginx 配置）
#
# 行为：
#   1) 移除 sites-enabled 软链
#   2) 移除 sites-available 配置 + htpasswd 文件
#   3) reload nginx（不卸载 nginx 包本身）
#   4) 询问是否卸载 nginx 包（默认 no）

set -u
set -o pipefail

NGINX_CONF="/etc/nginx/sites-available/lingxi-share"
NGINX_LINK="/etc/nginx/sites-enabled/lingxi-share"
HTPASSWD_FILE="/etc/nginx/.htpasswd"
PORT=8080

if [ "$(id -u)" -ne 0 ]; then
    echo "❌ 需要 root 权限" >&2
    exit 1
fi

echo "=== lingxi-share 卸载 ==="

# 1) 移除软链
if [ -L "$NGINX_LINK" ]; then
    rm -f "$NGINX_LINK"
    echo "→ 已移除: $NGINX_LINK"
else
    echo "→ 软链不存在，跳过"
fi

# 2) 移除配置 + htpasswd
if [ -f "$NGINX_CONF" ]; then
    rm -f "$NGINX_CONF"
    echo "→ 已移除: $NGINX_CONF"
fi

if [ -f "$HTPASSWD_FILE" ]; then
    rm -f "$HTPASSWD_FILE"
    echo "→ 已移除: $HTPASSWD_FILE"
fi

# 3) reload nginx（如果还在）
if command -v nginx >/dev/null 2>&1; then
    if nginx -t 2>/dev/null; then
        systemctl reload nginx 2>/dev/null && echo "→ nginx 已 reload"
    else
        echo "⚠️ nginx 配置有问题，请手动检查: sudo nginx -t" >&2
    fi
fi

# 4) 询问是否卸载 nginx 包
echo ""
read -p "是否卸载 nginx 包 (apt purge nginx)? (y/N) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    apt-get purge -y nginx nginx-common
    apt-get autoremove -y
    echo "→ nginx 已卸载"
else
    echo "→ 已跳过（nginx 包仍在系统里，可继续用作其他站点）"
fi

echo ""
echo "=== 卸载完成 ==="
echo "重新部署: install.sh"
