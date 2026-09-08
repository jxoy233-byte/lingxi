# lingxi-sync 一键定时同步

把 `/var/www/lingxi/` 保持与 `gitee.com/jxoy233/lingxi` / `github.com/jxoy233-byte/lingxi` 远程 main HEAD 完全一致，每 30 分钟一次。

## 目录结构

```
/root/scripts/lingxi-sync/           # 部署目录（start.sh 自动复制到这里）
├── lingxi-sync.sh                   # 同步逻辑（不要直接 cron 调）
├── run.sh                           # cron 入口（自动建 logs/ + 透传参数）
├── start.sh                         # 启动：部署 + 注册 cron + 部署日志清理
├── stop.sh                          # 停止：移除 cron（可选删除部署目录）
└── logs/
    └── lingxi-sync.log              # 同步日志（由 logrotate 或 run.sh 自清理管理）

/var/www/lingxi/               # 同步下来的项目源码（start.sh 首次跑时自动 clone）
/etc/logrotate.d/lingxi-sync         # 日志轮转配置（仅当系统有 logrotate 时部署）
```

## 日志清理策略

`start.sh` 部署时自动检测：

- **检测到 logrotate 命令** → 写 `/etc/logrotate.d/lingxi-sync` 配置（daily + rotate 7 + compress），`run.sh` 保持纯净
- **未检测到 logrotate** → 给 `run.sh` 末尾注入自清理段（日志 > 10MB 时 truncate 到最近 5000 行）

查看当前策略：

```bash
ls /etc/logrotate.d/lingxi-sync   # 存在 → logrotate 模式
grep "self-clean truncate" /root/scripts/lingxi-sync/run.sh  # 存在 → 自清理模式
```

## 快捷命令

### 🚀 启动（首次部署 / 恢复）

```bash
# 部署到 /root/scripts/lingxi-sync/ + 注册 cron + 立即跑一次同步
sudo /root/scripts/lingxi-sync/start.sh

# 仅部署不立即跑
sudo /root/scripts/lingxi-sync/start.sh --no-run
```

输出示例：

```
=== lingxi-sync 一键启动 ===
→ 复制脚本到 /root/scripts/lingxi-sync
→ 已创建日志目录: /root/scripts/lingxi-sync/logs
→ 已注册 cron: */30 * * * * /root/scripts/lingxi-sync/run.sh >> ...

=== 立即触发一次同步 ===
[lingxi-sync 2026-09-08 11:00:00] ========== 同步开始 ==========
[lingxi-sync 2026-09-08 11:00:00] Gitee 与 GitHub HEAD 一致 (abc12345)，使用 Gitee
[lingxi-sync 2026-09-08 11:00:35] ✅ 已同步到 abc12345
```

### 🛑 停止（移除 cron）

```bash
# 仅移除 cron，保留脚本和日志（之后还能 start.sh 重启）
sudo /root/scripts/lingxi-sync/stop.sh

# 移除 cron + 删除整个部署目录（脚本 + 日志 + 中间产物）
sudo /root/scripts/lingxi-sync/stop.sh --purge

# 删除不二次确认（脚本化场景）
sudo /root/scripts/lingxi-sync/stop.sh --purge -y
```

### 🔍 查看状态

```bash
# cron 注册情况
crontab -l | grep lingxi-sync

# 最近 20 行日志
tail -20 /root/scripts/lingxi-sync/logs/lingxi-sync.log

# 手动触发一次（不等 30 分钟）
/root/scripts/lingxi-sync/run.sh

# 看同步下来的 lingxi 项目
ls -la /var/www/lingxi/
```

## 三个脚本的职责分工

| 脚本 | 职责 | 调用方 |
|---|---|---|
| `lingxi-sync.sh` | 纯同步逻辑：选源 + clone/fetch + reset | run.sh / 手动调试 |
| `run.sh` | cron 入口：建 logs/ + （可选）自清理 truncate + 透传参数 | cron |
| `start.sh` | 一键启动：复制 + 部署日志清理策略 + 注册 cron + 可选立即跑 | 首次部署 |
| `stop.sh` | 一键停止：移除 cron + logrotate 配置 + 可选删除目录 | 卸载 |

## 退出码（监控 / 报警用）

| 退出码 | 含义 |
|--------|------|
| `0` | 成功 |
| `1` | 双源不可达（Gitee + GitHub 都 timeout） |
| `2` | 目录冲突（目标目录存在但不是 lingxi 根） |
| `3` | git 命令失败（clone / fetch / reset） |

## 失败处理策略

**任何非 0 退出码 = 跳过本轮**，**不重试 + 不污染 working tree**：

- `lingxi-sync.sh` 在每个失败点（选源 / clone / fetch / reset）都 `return 非 0`
- `run.sh` 用 `exec` 透传退出码，cron 不会重试
- cron 默认行为：失败 → 等下个 30 分钟周期自动重试
- 失败时本地仓库状态保持不变（reset --hard 是最后一步，前面任何失败都不动 HEAD/working tree）

举例：

- **Gitee + GitHub 都 timeout**（退码 1）→ 30 分钟后重试，可能就恢复了
- **`/var/www/lingxi/` 不是 lingxi 根**（退码 2）→ 需要人工干预（stop.sh → 删除冲突目录 → start.sh 重来）
- **磁盘满导致 git fetch 失败**（退码 3）→ 需要人工清理磁盘

接入 Prometheus / 监控时建议：

- 连续 3 次失败（≈ 1.5 小时网络挂掉）触发告警
- 退码 2 / 3 立即告警（不是网络问题，是配置 / 环境问题）
- 退码 1 在退码 0 后再次出现时告警（中间恢复又挂）

## 选源策略（与 frontend/electron/platform.js:selectRepoUrl 1:1 对齐）

1. 并发 `git ls-remote` 跑 Gitee + GitHub，各 3s timeout
2. 两边 SHA 一致 → 用 Gitee（国内快）
3. SHA 不一致 → fallback GitHub（拿到最新代码）
4. 任一不可达 → fallback 另一边
5. 两边都不通 → 退出码 1
