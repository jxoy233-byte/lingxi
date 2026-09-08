# lingxi-share-logs — nginx 日志 size-based 兜底清理

把 `/var/log/nginx/*.log` 每天扫一次，**单文件超过 100MB 时原子 truncate 到最近 10 万行**，防止突发流量单日撑爆日志。**与系统默认 logrotate 互补，不冲突**。

## 跟系统 logrotate 的分工

Ubuntu 装 nginx 时**已经自带** `/etc/logrotate.d/nginx`（daily + rotate 14 + compress），但它是**按时间轮转**（每天一次），应对不了单日突发流量——比如下载接口被爬一天就能写出 1-2GB。

| 工具 | 触发 | 策略 | 适用场景 |
|---|---|---|---|
| 系统 `logrotate` | 每天固定时间 | rotate 14 个旧文件 + gzip | 日积月累，磁盘总量控制 |
| **本套件** | 每天 3:17am | size-based truncate（> 100MB → 留 10 万行） | 单日突发流量，**兜底截断** |

两者独立运行：logrotate 处理历史文件压缩归档，本套件处理活日志体积上限。**先截后转**（3:17am 早于 logrotate 默认 ~6:25am），避免同一文件被两边同时操作。

## 目录结构

```
/root/scripts/lingxi-share-logs/     # 部署目录（start.sh 自动复制到这里）
├── clean-nginx-logs.sh              # 核心逻辑：扫描 + 原子 truncate
├── run.sh                           # cron 入口：建 logs/ + 透传参数
├── start.sh                         # 启动：部署 + 注册 cron + 立即跑
├── stop.sh                          # 停止：移除 cron + 可选 --purge
└── logs/
    └── clean-nginx-logs.log         # 清理日志（记录每个文件 size 变化）
```

## 快捷命令

### 🚀 启动（首次部署）

```bash
sudo /root/scripts/lingxi-share-logs/start.sh           # 部署 + 立即跑一次扫描
sudo /root/scripts/lingxi-share-logs/start.sh --no-run  # 仅部署不跑
```

输出示例：

```
=== lingxi-share-logs 一键启动 ===
→ 复制脚本到 /root/scripts/lingxi-share-logs
→ 已注册 cron: 17 3 * * * /root/scripts/lingxi-share-logs/run.sh >> ...

=== 立即触发一次扫描 ===
[clean-nginx-logs ...] ========== 开始扫描 /var/log/nginx ==========
[clean-nginx-logs ...]   skip: access.log (5242880 B ≤ 104857600 B)
[clean-nginx-logs ...]   skip: error.log (131072 B ≤ 104857600 B)
[clean-nginx-logs ...] ========== 扫描完成 ==========
=== 扫描退出码: 0 ===
```

### 🛑 停止

```bash
sudo /root/scripts/lingxi-share-logs/stop.sh            # 仅移除 cron
sudo /root/scripts/lingxi-share-logs/stop.sh --purge    # 拒绝（必须 --yes）
sudo /root/scripts/lingxi-share-logs/stop.sh --purge -y # 移除 cron + 删除部署目录
```

### 🔍 查看状态

```bash
crontab -l | grep lingxi-share-logs          # 看 cron 是否注册
tail -20 /root/scripts/lingxi-share-logs/logs/clean-nginx-logs.log  # 看清理日志
ls -lh /var/log/nginx/                       # 看当前活日志大小
/root/scripts/lingxi-share-logs/run.sh       # 手动触发一次（不等 3:17am）
```

## 调阈值

两个环境变量可覆盖默认值，无需改脚本：

```bash
# 50MB 阈值 + 留 5 万行（更激进，适合高频下载场景）
LOG_MAX_BYTES=$((50*1024*1024)) KEEP_LINES=50000 /root/scripts/lingxi-share-logs/run.sh

# 200MB 阈值 + 留 20 万行（更宽松，适合低频下载）
LOG_MAX_BYTES=$((200*1024*1024)) KEEP_LINES=200000 /root/scripts/lingxi-share-logs/run.sh
```

**怎么选阈值**：

- `LOG_MAX_BYTES` = 触发截断的下限。设小 = 频繁截断 = 丢失更多历史；设大 = 留给 logrotate 处理
- `KEEP_LINES` = 截断后保留的最近行数。nginx 单行紧凑格式 ~200-500B → 10 万行 ≈ 20-50MB

**建议**：低风险场景（公网下载、robots.txt 防爬）→ 默认即可；高风险场景（被恶意爬虫刷）→ 把 `LOG_MAX_BYTES` 调到 50MB、`KEEP_LINES` 调到 5 万行（更激进截断）。

永久改阈值：编辑 `clean-nginx-logs.sh` 顶部 `LOG_MAX_BYTES` / `KEEP_LINES` 默认值，然后 `start.sh` 重跑即可覆盖。

## 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 成功（所有文件处理完毕） |
| `1` | 参数错（不是 root） |
| `2` | `/var/log/nginx/` 不存在 |
| `3` | IO 错误（tail / mv 失败） |

接入监控时建议：

- 连续 3 天退码 3 → 告警（磁盘满 / IO 异常）
- 退码 2 → 检查 nginx 是否还在跑（可能意外卸载了）
- 退码 0 + 截断数 > 0 → 通知（说明被刷了，可考虑加 limit_rate）

## 为什么不用 truncate 命令而用 tail + mv

`truncate -s 0` 只清空文件但**保留文件位置（offset）**——如果 nginx 已经写到了位置 500MB，truncate 后 nginx 继续从 500MB 写，**整个文件变 sparse file**（前面 500MB 全是空洞），磁盘反而被撑得更大。

`tail -n KEEP_LINES` + `mv` 方案：

1. 读出最后 10 万行 → 写到 `.tmp.$$`
2. 原子 `mv .tmp.$$` 覆盖原文件
3. nginx 持有的 FD 指向同一 inode（mv 不改 inode），继续写
4. 整个过程零停机、零数据丢失窗口

## 注意事项

1. **必须 root**：要读 `/var/log/nginx/`（默认 640 + www-data adm）
2. **截断会丢历史**：100MB → 10 万行的过程中，被截掉的部分永久丢失——但如果日志已经大到 100MB，**保留全量也大概率没人去看**
3. **不处理 .gz / .数字 文件**：那些是 logrotate 已经轮转的旧文件，本套件不碰
4. **nginx 不需要 reload**：FD 一直有效，截断对 nginx 完全透明
5. **多个 nginx 实例**：本套件扫所有 `/var/log/nginx/*.log`，多实例只要日志都落这个目录就行
