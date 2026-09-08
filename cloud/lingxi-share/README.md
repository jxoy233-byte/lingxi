# lingxi-share — nginx 静态文件共享（配套 lingxi-sync）

把 `/var/www/lingxi/`（lingxi-sync 同步下来的项目目录）通过 nginx 共享到公网，供其他电脑下载。

## 部署

```bash
# 完全公开（任何人拿到链接都能下）
sudo /root/scripts/lingxi-share/install.sh

# 加 HTTP Basic Auth（弹框要用户名密码，用户名 lingxi）
sudo /root/scripts/lingxi-share/install.sh --auth
```

部署完：

- 浏览器访问 `http://你的公网IP:8080/` —— 看目录 + 点下载
- 命令行 `curl -O http://你的公网IP:8080/<文件名>`
- **一键下载整个项目**：`curl -O http://你的公网IP:8080/lingxi.tar.gz && tar -xzf lingxi.tar.gz`（macOS / Linux / Windows 10+ 通吃）

⚠️ **云服务器安全组**（阿里云 / 腾讯云 / AWS）必须放行 8080 端口

## 三种下载方式

### 方式 1：浏览器逐个点

打开 `http://你的公网IP:8080/`，看到一个文件列表，点哪个下哪个。

### 方式 2：单文件 curl

```bash
curl -O http://你的公网IP:8080/backend.tar.gz
```

### 方式 3：一键下载整个项目（推荐，跨平台）

lingxi-sync 每次跑完会在 `/var/www/lingxi/lingxi.tar.gz` 打一个包（自动排除 `.git` / `node_modules` / `.venv` 等大目录）。用户只下一行命令：

```bash
# 一行搞定：下载 + 解压 + 删 tarball
curl -O http://你的公网IP:8080/lingxi.tar.gz && tar -xzf lingxi.tar.gz && rm lingxi.tar.gz
```

**跨平台验证**：

| 系统 | curl 自带 | tar 自带 | 直接跑？ |
|---|---|---|---|
| **macOS** | ✅ | ✅ BSD tar | ✅ |
| **Linux** | ✅ | ✅ GNU tar | ✅ |
| **Windows 10+** | ✅ PowerShell 5+ | ✅ tar.exe | ✅ |
| **Windows 7/8** | ❌ | ❌ | 需装 Git for Windows |

**为什么不用 pull.sh / wget**：

- wget 在 macOS / Windows **不自带**（要 `brew install wget` 或 WSL）
- curl + tar 在**所有现代系统都自带**
- 单 URL `curl -O` 比起 wget 递归（要 `-r -np -nH -R index.html*` 一堆参数）简单 10 倍
- 「递归下载」其实根本不需要——服务端打 tar.gz 就一次到位

**注意**：lingxi.tar.gz 包含完整项目源码（不含 `.git` 历史），首次 sync 完成后 30 分钟内可下到；sync 进行中下载会拿到 503（保护机制）。

## 卸载

```bash
# 仅移除 lingxi-share 配置（nginx 本身保留）
sudo /root/scripts/lingxi-share/uninstall.sh

# 卸载配置 + 卸载 nginx 包
sudo /root/scripts/lingxi-share/uninstall.sh  # 看到问 y/N 时输入 y
```

## 配置说明

默认配置：

- **端口**：8080（避开常用端口）
- **目录**：`/var/www/lingxi`
- **目录浏览**：开启（`autoindex on`）
- **大小显示**：KB/MB（不是字节）
- **时间显示**：本地时区
- **主机名**：`_`（接受任意域名/IP）

如果要改路径 / 端口 / 加 HTTPS，直接编辑：

```bash
sudo vim /etc/nginx/sites-available/lingxi-share
sudo nginx -t && sudo systemctl reload nginx
```

## 常用 nginx 命令

```bash
sudo nginx -t                  # 配置语法检查
sudo systemctl reload nginx    # 重载（零停机）
sudo systemctl restart nginx   # 重启（短暂停机）
sudo systemctl status nginx    # 看运行状态
sudo tail -f /var/log/nginx/error.log   # 看错误日志
```

## 与 lingxi-sync 配合

`/var/www/lingxi/` 是 lingxi-sync 每 30 分钟同步一次的项目目录。装上 lingxi-share 后，**实时生效**：

- 别人下载到的就是你最新同步的 lingxi 代码
- 不用手动上传
- 多副本团队同步开发友好

### 并发安全：sync 进行中下载怎么办？

lingxi-sync 每 30 分钟会跑 `git fetch + reset --hard`，如果恰好有人在下载文件，下到一半文件被替换会拿到**损坏的 zip**。

**自动保护机制**（无需任何额外配置）：

- lingxi-sync 在 reset 前写锁文件 `/var/www/lingxi/.sync_in_progress`
- nginx 检测到锁文件 → 返回 `503 Service Unavailable` + `Retry-After: 60`
- 用户（curl / wget / 浏览器）等 60 秒后重试 → 拿到完整文件
- sync 完成后删锁文件（EXIT trap 保证任何路径退出都清锁）

**用户体验**：

```
$ curl -O http://IP:8080/lingxi.tar.gz
  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                 Dload  Upload   Total   Spent    Left  Speed
100   503  100   503    0     0   1500      0  --:--:-- --:--:-- --:--:-- --:--:--
curl: (22) The requested URL returned error: 503
# Retry-After: 60 → curl 不会自动等，需要重跑
```

用户最多等 60 秒（sync 一般 < 30 秒），期间会拿到 503 提示。**`curl` 默认不会按 Retry-After 自动重试**，但用户的常见用法是「`curl -O` + 手动重跑」或包到 shell 脚本里加 retry。`wget` 默认会按 Retry-After 自动重试一次（老 sync race 场景下 wget 体验更顺）。

## 注意事项

1. **完全公开** 意味着任何人能拿到链接就能下载。如果不想被爬虫，加 `--auth` 限速
2. **HTTP 明文传输**：如果分享敏感文件（API key 等），需要加 HTTPS（要域名 + 证书）
3. **磁盘空间**：公网可访问 = 任何人都能下。注意 `/var/www/lingxi` 大小
4. **限速**：默认无限制。如果担心被刷流量，加 `limit_rate` 配置
5. **并发安全**：sync 进行中下载会 503，由 lingxi-sync 的锁文件机制保护
