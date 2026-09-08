#!/usr/bin/env bash
# lingxi-sync.sh — 定时拉取 /var/www/lingxi/ 与远程 main 同步
#
# 设计要点（与 frontend/electron/platform.js:selectRepoUrl 同逻辑）：
#   1) 并发跑 `git ls-remote <gitee|github> refs/heads/main` 各 3s timeout
#   2) 两边 SHA 一致 → Gitee（国内快）；不一致 / 任一不可达 → fallback 另一源
#   3) 本地仓库不存在 → clone；存在但不是 lingxi → 拒绝（防覆盖）
#   4) 存在合法 → fetch + reset --hard origin/<branch>（不 merge / 不 rebase，
#      保证与远程 HEAD 完全一致；任何本地修改都会被冲掉，符合「源码镜像」定位）
#
# 用法（正常情况通过 start.sh 一键启动；手动调试直接 bash 调本脚本）：
#   /root/scripts/lingxi-sync/lingxi-sync.sh                  # 默认目录 /var/www/lingxi
#   /root/scripts/lingxi-sync/lingxi-sync.sh /path/to/lingxi  # 自定义目录
#   LINGXI_SYNC_TARGET=/opt/lingxi /root/scripts/lingxi-sync/lingxi-sync.sh  # 环境变量覆盖
#
# 退出码：0 成功 / 1 网络双源不可达 / 2 目录冲突 / 3 git 命令失败

set -u

# ─────────── 路径配置 ────────────
# 优先级：命令行参数 > LINGXI_SYNC_TARGET 环境变量 > 默认 /var/www/lingxi
# 不依赖 $HOME：cron 环境下 $HOME 可能是 / 或 /root，硬编码更稳。
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
TARGET_DIR="${1:-${LINGXI_SYNC_TARGET:-/var/www/lingxi}}"
BRANCH="main"
REMOTE_GITEE="https://gitee.com/jxoy233/lingxi.git"
REMOTE_GITHUB="https://github.com/jxoy233-byte/lingxi.git"
LOG_PREFIX="[lingxi-sync $(date '+%Y-%m-%d %H:%M:%S')]"

# log 显式走 stderr，避免被「命令替换 $()」误捕
log() { printf '%s %s\n' "$LOG_PREFIX" "$*" >&2; }

# ─────────── 环境校验 ────────────
# 比「双源不可达」更早报错的场景：系统没装 git / timeout / mktemp
# 这些错误一般不会出现（ubuntu 默认都有），但显式校验能让 root cause 清晰
command -v git >/dev/null 2>&1 || { log "❌ git 未安装（apt-get install -y git）"; exit 3; }
command -v timeout >/dev/null 2>&1 || { log "❌ timeout 未安装（apt-get install -y coreutils）"; exit 3; }
command -v mktemp >/dev/null 2>&1 || { log "❌ mktemp 未安装"; exit 3; }

# ─────────── 1. 取 SHA helper（单源，3s timeout）───────────
fetch_sha() {
    local url="$1"
    timeout 3 git ls-remote "$url" "refs/heads/$BRANCH" 2>/dev/null \
        | awk '$2 == "refs/heads/'"$BRANCH"'" {print $1; exit}'
}

# ─────────── 2. selectRepoUrl（同 platform.js:697）───────────
# ⚠️ 不能用 `local var=$(fetch) &` —— bash 命令替换 $() 在子 shell 跑，
#   & 后台的子 shell stdout 不回流到父 shell 变量，结果永远是空。
select_repo_url() {
    local gitee_tmp github_tmp
    gitee_tmp=$(mktemp)
    github_tmp=$(mktemp)
    # EXIT trap 兜底：函数任何路径退出（包括 set -u / 信号 / 异常）都清理临时文件
    trap "rm -f '$gitee_tmp' '$github_tmp'" EXIT

    # 并发跑（直接后台命令，不包在 $() 里）
    fetch_sha "$REMOTE_GITEE"  > "$gitee_tmp"  2>/dev/null &
    local pid_gitee=$!
    fetch_sha "$REMOTE_GITHUB" > "$github_tmp" 2>/dev/null &
    local pid_github=$!
    wait "$pid_gitee" 2>/dev/null || true
    wait "$pid_github" 2>/dev/null || true

    local gitee_sha github_sha
    gitee_sha=$(cat "$gitee_tmp")
    github_sha=$(cat "$github_tmp")

    if [ -n "$gitee_sha" ] && [ -n "$github_sha" ] && [ "$gitee_sha" = "$github_sha" ]; then
        log "Gitee 与 GitHub HEAD 一致 (${gitee_sha:0:8})，使用 Gitee"
        printf '%s\n' "$REMOTE_GITEE"
        return 0
    fi
    if [ -n "$gitee_sha" ] && [ -n "$github_sha" ]; then
        log "⚠️ Gitee HEAD ${gitee_sha:0:8} 与 GitHub HEAD ${github_sha:0:8} 不一致（镜像同步延迟），fallback 到 GitHub"
        printf '%s\n' "$REMOTE_GITHUB"
        return 0
    fi
    if [ -z "$gitee_sha" ] && [ -n "$github_sha" ]; then
        log "⚠️ Gitee ls-remote 失败，fallback 到 GitHub"
        printf '%s\n' "$REMOTE_GITHUB"
        return 0
    fi
    if [ -n "$gitee_sha" ] && [ -z "$github_sha" ]; then
        log "⚠️ GitHub ls-remote 失败，使用 Gitee"
        printf '%s\n' "$REMOTE_GITEE"
        return 0
    fi
    log "❌ Gitee 和 GitHub 都不可达，请检查网络"
    return 1
}

# ─────────── 3. 校验合法 lingxi 根（同 platform.js:187）───────────
is_valid_project_root() {
    local dir="$1"
    [ -f "$dir/backend/pyproject.toml" ] && [ -f "$dir/docker-compose.yml" ]
}

# ─────────── 3.6 删除部署期产物（云端不需要的目录）───────────
# 与 platform.js:_removeDeploymentArtifacts 行为对齐：
#   - 每次 sync 成功后调用（clone + reset 两路都触发）
#   - 失败仅 warn 不抛（缺失不影响服务运行）
#   - 列表驱动：未来新增「服务端不要的目录」往 DEPLOY_ARTIFACTS 里加一行即可
DEPLOY_ARTIFACTS="frontend cloud"
_remove_deployment_artifacts() {
    local artifact
    for artifact in $DEPLOY_ARTIFACTS; do
        local dir_path="$TARGET_DIR/$artifact"
        if [ ! -e "$dir_path" ]; then
            continue  # 已经是干净状态，跳过
        fi
        if rm -rf "$dir_path" 2>/dev/null; then
            log "🗑️ 已删除 $artifact/（部署期产物，云端不需要）"
        else
            log "⚠️ 删除 $artifact/ 失败（不影响 sync 本身）"
        fi
    done
    # ⚠️ 强制刷盘：rm -rf 命令返回 ≠ 目录 metadata 已落盘。内核 write-back
    #   缓存可能让 tar 紧接着 readdir 时拿到旧 stat，触发 "file changed as
    #   we read it" race。sync 等价于 fsync 整个 target dir 的元数据，
    #   保证 tar 看到的目录状态是 rm 真正完成后的状态。
    sync
}

# ─────────── 3.5 打包 lingxi.tar.gz（用户 curl 一键下载）───────────
# 设计：sync 成功后自动打包到 $TARGET_DIR/lingxi.tar.gz
#   - 排除大目录：.git / node_modules / __pycache__ / .venv / dist / build
#   - 排除锁文件本身 + 上一次的 lingxi.tar.gz（避免递归包含）
#   - 原子写：先打 .tmp 再 mv，避免半截文件
#   - tar 失败不阻断 sync（sync 已成功，tar 只是给用户多一个下载入口）
#
# 并发安全：sync 进行中 → 锁文件存在 → nginx 返 503 → 用户拿不到半截 tar.gz
#
# ⚠️ 关键：用 `tar -C "$TARGET_DIR"` 切目录，不要依赖调用方的 CWD
#   - cron 跑时 CWD = /root（root home），如果直接用 tar ... . 就会去打包 /root/
#   - 用 -C 强制 tar 自己切到 TARGET_DIR，shell 的 CWD 不动
#   - 同时捕获 stderr 进日志，失败时能看到具体原因（之前 2>/dev/null 吞了）
_package_targz() {
    local pkg="$TARGET_DIR/lingxi.tar.gz"
    # ⚠️ 关键：tmp 文件放 /tmp 而非 $TARGET_DIR
    #   原方案 `pkg_tmp="$TARGET_DIR/lingxi.tar.gz.tmp.$$"` 会触发 GNU tar
    #   "file changed as we read it" 假阳性：tar open(O_CREAT) 写 output 文件
    #   → 改 input 目录的 entry list + mtime → 紧接着 readdir 拿到的 stat
    #   与刚 stat 的不一致 → tar 报 file changed（即使没改 exclude 也复现）
    #   改放 /tmp 后，tar 的 output create 与 input readdir 完全解耦，race 消失。
    #   跨 fs 的 mv 是 copy+delete；50MB 量级 < 200ms，可接受。
    local pkg_tmp="/tmp/lingxi-$$.tar.gz"
    local pkg_stderr="/tmp/lingxi-$$.tar.gz.stderr"
    local tar_err tar_rc

    # 预检：TARGET_DIR 必须存在（clone 失败时也不会到这一步，但兜底）
    if [ ! -d "$TARGET_DIR" ]; then
        log "⚠️ 打包跳过：$TARGET_DIR 不存在"
        return 0
    fi

    # tar -C 切到 TARGET_DIR；output 写 /tmp；捕获 stderr；记录退出码
    tar -C "$TARGET_DIR" -czf "$pkg_tmp" \
        --exclude='lingxi.tar.gz' \
        --exclude='lingxi.tar.gz.tmp.*' \
        --exclude='.git' \
        --exclude='.sync_in_progress' \
        --exclude='node_modules' \
        --exclude='__pycache__' \
        --exclude='.venv' \
        --exclude='venv' \
        --exclude='dist' \
        --exclude='build' \
        --exclude='.pytest_cache' \
        --exclude='.mypy_cache' \
        --exclude='.ruff_cache' \
        --exclude='frontend' \
        --exclude='cloud' \
        . 2> "$pkg_stderr"
    tar_rc=$?
    tar_err=$(cat "$pkg_stderr" 2>/dev/null)
    rm -f "$pkg_stderr"

    if [ "$tar_rc" -ne 0 ]; then
        log "⚠️ 打包 lingxi.tar.gz 失败（tar 退码 ${tar_rc}）：${tar_err:-<空 stderr>}"
        rm -f "$pkg_tmp"
        return 0
    fi

    mv -f "$pkg_tmp" "$pkg"
    local size
    size=$(stat -c%s "$pkg" 2>/dev/null || stat -f%z "$pkg" 2>/dev/null || echo "?")
    log "📦 已打包: lingxi.tar.gz (${size} 字节)"
}

# ─────────── 4. 主流程 ────────────
main() {
    log "========== 同步开始 =========="
    log "脚本目录: $SCRIPT_DIR"
    log "目标目录: $TARGET_DIR"

    # 锁文件：sync 进行中存在，nginx 检测到则返 503 + Retry-After
    # 让正在下载的用户知道「等会儿再来」，避免下到半残 zip
    LOCK_FILE="$TARGET_DIR/.sync_in_progress"
    # EXIT trap 兜底：任何路径退出（包括成功 / 失败 / 信号）都清锁
    trap "rm -f '$LOCK_FILE'" EXIT

    # 写锁文件（先建目录再写，TARGET_DIR 可能还不存在）
    if [ -d "$TARGET_DIR" ]; then
        touch "$LOCK_FILE" || log "⚠️ 无法写锁文件: $LOCK_FILE"
    fi

    local repo_url
    if ! repo_url=$(select_repo_url); then
        return 1
    fi
    log "使用源: $repo_url"

    if [ ! -d "$TARGET_DIR" ]; then
        log "目录不存在，执行 clone"
        local parent_dir
        parent_dir=$(dirname "$TARGET_DIR")
        if [ -z "$parent_dir" ] || [ "$parent_dir" = "/" ]; then
            log "❌ 父目录非法: '$parent_dir'"
            return 3
        fi
        mkdir -p "$parent_dir" || { log "❌ 创建父目录失败: $parent_dir"; return 3; }
        # clone 完后才能写锁（目录刚建出来），所以这里补一次
        if ! git clone --branch "$BRANCH" --depth 1 "$repo_url" "$TARGET_DIR"; then
            log "❌ git clone 失败"
            return 3
        fi
        touch "$LOCK_FILE" || true
        log "✅ clone 成功"
        _remove_deployment_artifacts
        _package_targz
        return 0
    fi

    if ! is_valid_project_root "$TARGET_DIR"; then
        log "❌ $TARGET_DIR 已存在但不是合法 lingxi 根，拒绝覆盖"
        return 2
    fi

    cd "$TARGET_DIR" || { log "❌ cd 失败: $TARGET_DIR"; return 3; }

    local dirty
    dirty=$(git status --porcelain 2>/dev/null | head -5 || true)
    if [ -n "$dirty" ]; then
        log "⚠️ 本地有未提交改动（将一并被 reset 冲掉）："
        git status --porcelain 2>/dev/null | head -5 | while IFS= read -r line; do
            log "    $line"
        done
    fi

    local current_remote
    current_remote=$(git remote get-url origin 2>/dev/null || echo "")
    if [ "$current_remote" != "$repo_url" ]; then
        log "修正 origin remote: '$current_remote' → '$repo_url'"
        if ! git remote set-url origin "$repo_url"; then
            log "❌ git remote set-url 失败"
            return 3
        fi
    fi

    if ! git fetch --depth 1 origin "$BRANCH"; then
        log "❌ git fetch 失败"
        return 3
    fi

    if ! git reset --hard "origin/$BRANCH"; then
        log "❌ git reset 失败"
        return 3
    fi

    local new_sha
    new_sha=$(git rev-parse HEAD)
    log "✅ 已同步到 ${new_sha:0:8}"
    _remove_deployment_artifacts
    _package_targz
    return 0
}

main "$@"
