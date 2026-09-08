#!/usr/bin/env bash
# install.sh — 一键部署 nginx 静态文件共享服务（配套 lingxi-sync）
#
# 行为：
#   1) 校验 root + apt 可用
#   2) 装 nginx
#   3) 写入配置：监听 8080，root 指 /var/www/lingxi，开启目录浏览
#   4) 启用 + 重载 nginx
#   5) 防火墙放行 8080
#
# 用法：
#   sudo ./install.sh           # 默认配置
#   sudo ./install.sh --auth    # 加 basic auth（用户名 lingxi，密码运行时输入）

set -u
set -o pipefail

# ─────────── 0. 校验 ────────────
if [ "$(id -u)" -ne 0 ]; then
    echo "❌ 需要 root 权限" >&2
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    echo "❌ 仅支持 Ubuntu/Debian（apt-get 不存在）" >&2
    exit 1
fi

# 路径配置
SHARE_DIR="/var/www/lingxi"
NGINX_CONF="/etc/nginx/sites-available/lingxi-share"
NGINX_LINK="/etc/nginx/sites-enabled/lingxi-share"
PORT=8080

DO_AUTH=false
for arg in "$@"; do
    case "$arg" in
        --auth) DO_AUTH=true ;;
        -h|--help)
            echo "用法: sudo $0 [--auth]"
            echo "  --auth   启用 HTTP Basic Auth（用户 lingxi）"
            exit 0 ;;
        *) echo "❌ 未知参数: $arg" >&2; exit 1 ;;
    esac
done

# ─────────── 1. 装 nginx ────────────
echo "→ 检查 nginx 是否已装"
if ! command -v nginx >/dev/null 2>&1; then
    echo "→ 装 nginx"
    apt-get update -y || { echo "❌ apt-get update 失败" >&2; exit 1; }
    apt-get install -y nginx || { echo "❌ apt install nginx 失败" >&2; exit 1; }
else
    echo "→ nginx 已装"
fi

# ─────────── 2. 写入配置 ────────────
# 检查 share 目录是否存在；不存在也要建（nginx 启动时不报错，但访问会 404）
if [ ! -d "$SHARE_DIR" ]; then
    echo "⚠️ $SHARE_DIR 不存在，创建空目录（lingxi-sync 首次跑时会 clone 进来）"
    mkdir -p "$SHARE_DIR"
fi

# 确保 nginx 日志目录和文件存在（nginx -t 会真打开 log 文件做完整加载）
# 刚装 nginx 时 /var/log/nginx/ 可能没建（postinst 漏跑 / 手动装 / 升级异常）
NGINX_LOG_DIR="/var/log/nginx"
if [ ! -d "$NGINX_LOG_DIR" ]; then
    echo "→ 创建 nginx 日志目录: $NGINX_LOG_DIR"
    mkdir -p "$NGINX_LOG_DIR" || { echo "❌ 创建 $NGINX_LOG_DIR 失败" >&2; exit 1; }
fi
for log_file in "$NGINX_LOG_DIR/access.log" "$NGINX_LOG_DIR/error.log"; do
    if [ ! -f "$log_file" ]; then
        touch "$log_file" || { echo "❌ touch $log_file 失败" >&2; exit 1; }
    fi
done
# 修正所有权：Ubuntu nginx 包默认 www-data:adm；其他发行版可能是 nginx:nginx
# chown 失败不立即 abort（用户可能用其他方式跑 nginx）
chown -R www-data:adm "$NGINX_LOG_DIR" 2>/dev/null \
    || chown -R nginx:nginx "$NGINX_LOG_DIR" 2>/dev/null \
    || echo "⚠️ 修正 /var/log/nginx 所有权失败（用户可能自定义 nginx user）" >&2
chmod 640 "$NGINX_LOG_DIR"/*.log

AUTH_BLOCK=""
if $DO_AUTH; then
    # 装 htpasswd 工具
    if ! command -v htpasswd >/dev/null 2>&1; then
        apt-get install -y apache2-utils
    fi
    HTPASSWD_FILE="/etc/nginx/.htpasswd"
    if [ ! -f "$HTPASSWD_FILE" ]; then
        echo "→ 创建 HTTP Basic Auth 用户"
        htpasswd -c "$HTPASSWD_FILE" lingxi || { echo "❌ 创建 htpasswd 失败" >&2; exit 1; }
    else
        echo "→ HTTP Basic Auth 已存在 ($HTPASSWD_FILE)"
    fi
    AUTH_BLOCK=$(cat <<AUTH_EOF
    auth_basic "Lingxi Share";
    auth_basic_user_file $HTPASSWD_FILE;
AUTH_EOF
)
fi

# 写入配置（删旧配置再写，保持幂等）
# 关键设计：检测到 .sync_in_progress 锁文件 → 返回 503 + Retry-After
# 配套 lingxi-sync.sh：sync 进行中会写这个锁文件，结束后删
# 用户体验：sync 撞上下下载 → 503 等 60s 重试 → 拿到完整文件，不会下到半残 zip
#
# 注意：nginx 不允许 add_header 放在 if 块内（if 只允许 return/rewrite/set/break）
# 改用 error_page + 命名 location 拦截 503，header 加在 location 块里
cat > "$NGINX_CONF" <<EOF
server {
    listen $PORT;
    server_name _;

    root $SHARE_DIR;
    autoindex on;
    autoindex_exact_size off;
    autoindex_localtime on;
$AUTH_BLOCK

    # 检测锁文件 → 直接返 503
    if (-f \$document_root/.sync_in_progress) {
        return 503;
    }

    # 拦截 503 → 命名 location 加 Retry-After 头
    error_page 503 @sync_in_progress;

    location @sync_in_progress {
        default_type text/plain;
        add_header Retry-After 60 always;
        return 503 "Sync in progress, please retry in 60 seconds\n";
    }

    location / {
        try_files \$uri \$uri/ =404;
    }
}
EOF
echo "→ 已写入配置: $NGINX_CONF"

# 启用配置（软链）
if [ ! -L "$NGINX_LINK" ]; then
    ln -s "$NGINX_CONF" "$NGINX_LINK"
    echo "→ 已启用配置: $NGINX_LINK"
fi

# ─────────── 3. 测配置 + 重载 ────────────
# 确保 nginx 在跑（新装 systemd 可能没 enable；reload 会在服务未跑时静默失败）
if ! systemctl is-active --quiet nginx; then
    echo "→ nginx 服务未运行，尝试启动"
    systemctl enable --now nginx || { echo "❌ 启动 nginx 服务失败" >&2; exit 1; }
fi

if nginx -t; then
    systemctl reload nginx || { echo "❌ nginx reload 失败" >&2; exit 1; }
    echo "→ nginx 配置语法 OK + 已 reload"
else
    echo "❌ nginx 配置语法错误，请检查: sudo nginx -t" >&2
    exit 1
fi

# ─────────── 4. 防火墙 ────────────
if command -v ufw >/dev/null 2>&1; then
    # 检测 ufw 是否激活
    if ufw status 2>/dev/null | grep -q "Status: active"; then
        ufw allow "$PORT/tcp" 2>/dev/null
        echo "→ ufw 已放行 $PORT/tcp"
    else
        echo "→ ufw 未激活，跳过（云服务器请在控制台安全组放行 $PORT）"
    fi
else
    echo "→ ufw 未装，跳过（云服务器请在控制台安全组放行 $PORT）"
fi

echo ""
echo "=== 部署完成 ==="
echo "共享目录: $SHARE_DIR"
echo "访问地址: http://你的公网IP:$PORT/"
echo ""
echo "⚠️ 别忘了：云服务器安全组（阿里云 / 腾讯云 / AWS）也要放行 $PORT 端口"
echo ""
echo "禁用: sudo rm $NGINX_LINK && sudo systemctl reload nginx"
