import json
import os
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional, Set, Dict, Deque

from ChatMe.LoggingManager.logging_config import get_logger


class SandboxPoolTimeoutError(RuntimeError):
    """沙盒池无可用容器（acquire 超时）。RuntimeError 子类，调用方 except Exception 仍能 catch。"""


class SandboxPool:
    """
    沙盒容器池（共享容器 + 每容器 N 并发）。

    并发模型（v2，2026-07）：
    - 池里有 K 个长跑容器（min_size ≤ K ≤ max_size）
    - 每个容器挂一个 threading.Semaphore(per_container_concurrency) 控制单容器并发
    - acquire() 返回 (cid, slot)：调用方拿到 cid + 占一个 slot，但**不独占容器**，
      其他线程可以同时往同一个容器塞 docker exec（受 slot 上限约束）
    - 全局并发上限 = K × per_container_concurrency

    与 v1 的区别：
    - v1: pool.pop() 在锁内、exec 在锁内、append 在锁内 → 一个容器一次只能跑一个命令
    - v2: pop + 抢 slot 即可，exec 在锁外 → 同一容器可并发 N 个 docker exec

    典型配置（default）：
    - min_size=1（默认 1 个常驻）, max_size=3（峰值 3 个）, per_container_concurrency=8
    - 基线并发 1×8=8，峰值并发 3×8=24
    - 触发扩容：所有现有容器 slot 都满且总容器数 < max_size → 新建一个
    - 触发 GC：temp 容器闲置 > 5min → 自动销毁（不低于 min_size）

    env 覆盖：
    - SANDBOX_MIN_SIZE / SANDBOX_MAX_SIZE / SANDBOX_PER_CONTAINER_CONCURRENCY
    - SANDBOX_CMD_TIMEOUT / SANDBOX_CODE_TIMEOUT
    """

    _logger = get_logger("mcp_server")

    def __init__(
        self,
        size: int = 1,                       # 兼容旧 API：等价于 min_size，默认 1 个容器
        image: str = "chatme-python-sandbox:latest",
        skills_path: Optional[str] = None,
        cached_path: Optional[str] = None,
        config_path: Optional[str] = None,
        max_size: Optional[int] = None,
        per_container_concurrency: Optional[int] = None,
    ):
        self.image = image

        # __file__ = backend/ChatMe/ChatWorkflow/mcps/CodeSandboxPool.py
        # 4 层 .parent 上去 = backend/
        backend_root = Path(__file__).resolve().parents[3]
        # 5 层 .parent 上去 = 项目根（用来定位 sandbox/）
        top_root = Path(__file__).resolve().parents[4]
        self.skills_path = os.path.abspath(skills_path or backend_root / "skills")
        self.cached_path = os.path.abspath(cached_path or backend_root / "cached")
        self.config_path = os.path.abspath(config_path or backend_root / ".chatme" / "config.json")
        self.logs_path = os.path.abspath(config_path or backend_root / ".chatme" / "logs")
        # 自动生成的 sandbox-only config（只含 skills 段，权限 600，不入 git）
        self.sandbox_config_path = os.path.abspath(top_root / "sandbox" / ".sandbox-config.json")

        # 从 host config.json 抽取 skills 段，生成 sandbox-only 配置
        self._generate_sandbox_config()

        # env 覆盖：min_size（兼容 size 参数）+ max_size + per_container_concurrency
        # 默认 max_size = 3（峰值 3 个容器），需要固定不扩可显式传 max_size=size
        self.min_size = int(os.getenv("SANDBOX_MIN_SIZE", str(size)))
        default_max = max_size if max_size is not None else 3
        self.max_size = int(os.getenv("SANDBOX_MAX_SIZE", str(default_max)))
        self.per_container_concurrency = int(
            os.getenv("SANDBOX_PER_CONTAINER_CONCURRENCY", str(per_container_concurrency or 8))
        )
        # 防御：min 不能超过 max
        self.min_size = min(self.min_size, self.max_size)
        # 防御：min_size 至少 1（池不能为空，否则首次 acquire 必定超时）
        self.min_size = max(self.min_size, 1)

        self.cmd_timeout = int(os.getenv("SANDBOX_CMD_TIMEOUT", "120"))
        self.code_timeout = int(os.getenv("SANDBOX_CODE_TIMEOUT", "300"))

        # 池状态
        self._pool_lock = threading.Lock()
        self._pool_cond = threading.Condition(self._pool_lock)
        # idle cid 队列（deque 支持 O(1) popleft）
        self.idle_containers: Deque[str] = deque()
        # cid → Semaphore，控制单容器并发
        self.container_sems: Dict[str, threading.Semaphore] = {}
        # cid → 是否为 temp（临时扩容产生的，空闲会被 GC）
        self.temp_containers: Set[str] = set()
        # 所有已知 cid（含 idle + in-use）
        self.all_containers: Set[str] = set()
        # 容器最近一次归还时间戳（用于 LRU GC）
        self.last_released_ts: Dict[str, float] = {}

        # 预启动 min_size 个长跑容器
        for _ in range(self.min_size):
            cid = self._create_container()
            if cid:
                self._register_container(cid, is_temp=False)

        # 启动后台 GC 线程：回收闲置 > 5 分钟的 temp 容器
        self._gc_thread = threading.Thread(
            target=self._gc_loop, name="SandboxPool-GC", daemon=True
        )
        self._gc_stop = threading.Event()
        self._gc_thread.start()

        print(
            f"[SandboxPool] 初始化完成: min_size={self.min_size}, max_size={self.max_size}, "
            f"per_container_concurrency={self.per_container_concurrency}, "
            f"实际启动容器数={len(self.all_containers)}, "
            f"全局理论并发={len(self.all_containers) * self.per_container_concurrency}"
        )

    # =========================================================================
    # 容器注册 / 创建 / 销毁
    # =========================================================================

    def _register_container(self, cid: str, is_temp: bool) -> None:
        """注册新创建的 cid 到池子数据结构。必须在 _pool_lock 内调用。"""
        if not cid:
            return
        self.all_containers.add(cid)
        self.idle_containers.append(cid)
        self.container_sems[cid] = threading.Semaphore(self.per_container_concurrency)
        self.last_released_ts[cid] = time.monotonic()
        if is_temp:
            self.temp_containers.add(cid)

    def _create_container(self) -> Optional[str]:
        """
        启动一个常驻容器：
        - mount skills(ro) + DataAnalysis(rw) + cached(rw) + sandbox-only config + logs
        - 容器内能看到：/skills, /cached, /.chatme/config.json（仅 skills 段）, /.chatme/logs
        - DataAnalysis 目录允许 skill 内配置函数写入跨会话配置，其余 skills 保持只读
        - ChatMeConfig / LoggingManager 已通过 Dockerfile COPY 进 site-packages
        - DataAnalysis skill.md 已通过 Dockerfile COPY 进 site-packages/skills/DataAnalysis
        """
        try:
            self._generate_sandbox_config()

            cmd = [
                "docker", "run", "-d",
                # skills 源码默认只读：保护其他 skill；随后单独覆盖 DataAnalysis 为可写
                "-v", f"{self.skills_path}:/skills:ro",
                # DataAnalysis 内置配置函数需要保存跨会话数据库配置
                "-v", f"{os.path.join(self.skills_path, 'DataAnalysis')}:/skills/DataAnalysis:rw",
                # cached 读写：用户上传立即可见，沙盒生成图表立即给用户
                "-v", f"{self.cached_path}:/cached:rw",
                # sandbox-only config（仅 skills 段，不含 llm/oss/app）
                "-v", f"{self.sandbox_config_path}:/.chatme/config.json:ro",
                # 日志：容器内写 /.chatme/logs，host 上落到 backend/.chatme/logs
                "-v", f"{self.logs_path}:/.chatme/logs:rw",
                # 工作目录约束：PYTHONPATH=/ 让 /cached、/skills 直接可 import，
                # WORKDIR=/ 让代码中的相对路径（如 open('cached/xxx')）也能解析。
                # 不再挂 tmpfs —— 代码直接写到根目录 /code.py，跟 /cached、/skills 同级
                "-e", "PYTHONPATH=/",
                # 用于访问 host 上的后端 VL 模型（127.0.0.1:8211）
                "--add-host=host.docker.internal:host-gateway",
                self.image,
                "sleep", "infinity"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            container_id = result.stdout.strip()
            self._logger.debug(f"[SandboxPool] 创建容器: {container_id}")
            return container_id
        except Exception as e:
            self._logger.warning(f"[SandboxPool] 创建容器失败: {e}")
            return None

    def _is_container_running(self, cid: str) -> bool:
        """快速检查容器是否在跑（不抛异常）。"""
        try:
            result = subprocess.run(
                ["docker", "inspect", cid, "--format", "{{.State.Running}}"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() == "true"
        except Exception:
            return False

    def _destroy_container(self, cid: str) -> None:
        """docker rm -f 容器，best-effort。"""
        try:
            subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=5)
        except Exception:
            pass

    # =========================================================================
    # 核心：acquire / release（共享容器 + slot 模型）
    # =========================================================================

    def _acquire(self, timeout: float = 30.0) -> str:
        """
        取一个 cid + 占一个 slot。

        流程：
        1. 在 idle 队列里找有空闲 slot 的容器（遍历直到找到或转一圈）
        2. 如果都满且 all_containers < max_size → 临时扩容新建一个
        3. 否则等 pool_cond.notify()（release 时触发）
        4. timeout 内拿到 cid + slot → 返回
        5. 超时 → raise SandboxPoolTimeoutError

        注意：必须在 _pool_lock 内调用整个循环。Semaphore.acquire(blocking=False)
        拿到 slot 后立即在锁内返回，避免后续线程看到已分配 cid 又抢。
        """
        deadline = time.monotonic() + timeout
        seen: Set[str] = set()  # 本轮已尝试的 cid，避免在同一轮里重复扫同一个

        while True:
            # 扫一遍 idle 队列，找有空闲 slot 的容器
            scanned = 0
            while self.idle_containers and scanned < len(self.idle_containers) + len(seen):
                cid = self.idle_containers.popleft()
                scanned += 1
                if cid in seen:
                    # 本轮已扫过，放回队尾
                    self.idle_containers.append(cid)
                    continue
                seen.add(cid)

                sem = self.container_sems.get(cid)
                if sem is None:
                    # cid 已被 GC 销毁，丢弃
                    continue

                # 抢一个 slot（非阻塞；满了就放回队尾，本轮不再试它）
                if sem.acquire(blocking=False):
                    return cid
                # slot 满，把 cid 放回 idle 队列末尾（其他容器可能还有空）
                self.idle_containers.append(cid)

            # idle 队列里没有可用 slot；尝试临时扩容
            if len(self.all_containers) < self.max_size:
                new_cid = self._create_container()
                if new_cid:
                    self._register_container(new_cid, is_temp=True)
                    # 刚注册就在 idle 队尾；下一轮扫描会处理它
                    continue  # 不 wait，立即重试

            # 真的没资源了：等 release() notify
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SandboxPoolTimeoutError(
                    f"No available containers in pool "
                    f"(min_size={self.min_size}, max_size={self.max_size}, "
                    f"all_containers={len(self.all_containers)}, "
                    f"per_container_concurrency={self.per_container_concurrency})"
                )
            seen.clear()  # 新一轮重新扫
            self._pool_cond.wait(timeout=remaining)

    def _release(self, cid: str) -> None:
        """
        释放 slot + 把 cid 放回 idle 队列，notify 等待中的 acquire。
        如果容器已不在 all_containers（被 GC 销毁了），slot 直接丢弃即可。
        """
        with self._pool_lock:
            sem = self.container_sems.get(cid)
            if sem is not None:
                sem.release()
            if cid in self.all_containers:
                self.idle_containers.append(cid)
                self.last_released_ts[cid] = time.monotonic()
            self._pool_cond.notify()

    # =========================================================================
    # GC：回收闲置 temp 容器
    # =========================================================================

    def _gc_loop(self) -> None:
        """后台线程：每 60s 扫一次，回收闲置 > 5min 的 temp 容器（不低于 min_size）。"""
        IDLE_THRESHOLD_SEC = 300  # 5 分钟
        while not self._gc_stop.wait(60):
            try:
                self._gc_once(IDLE_THRESHOLD_SEC)
            except Exception as e:
                self._logger.warning(f"[SandboxPool] GC 异常: {e}")

    def _gc_once(self, idle_threshold_sec: float) -> None:
        now = time.monotonic()
        with self._pool_lock:
            # 不能缩到 min_size 以下
            if len(self.all_containers) <= self.min_size:
                return
            # 找可回收的 temp 容器：必须在 idle 队列里（不在被借用），且闲置超阈值
            to_destroy = []
            for cid in list(self.temp_containers):
                if len(self.all_containers) - len(to_destroy) <= self.min_size:
                    break
                last_ts = self.last_released_ts.get(cid, now)
                if now - last_ts < idle_threshold_sec:
                    continue
                # 必须不在被借用（不在 in-use），只看 idle 队列里是否存在
                if cid not in self.idle_containers:
                    continue
                to_destroy.append(cid)

            for cid in to_destroy:
                # 从数据结构移除
                self.idle_containers.remove(cid)
                self.all_containers.discard(cid)
                self.temp_containers.discard(cid)
                self.container_sems.pop(cid, None)
                self.last_released_ts.pop(cid, None)
                # 实际销毁
                self._destroy_container(cid)
                self._logger.debug(f"[SandboxPool] GC 销毁闲置 temp 容器: {cid}")

    # =========================================================================
    # 公共 API：execute / execute_command（同步签名保持不变）
    # =========================================================================

    def execute(self, code: str, language: str = "python") -> str:
        """
        沙盒执行 Python / JS 代码。

        与 v1 的区别：acquire/release 取代 pop/append，exec 在锁外执行，
        所以同一容器可以并发跑多个 docker exec（受 per_container_concurrency 限制）。
        """
        cid = self._acquire()
        try:
            return self._execute_in_container(cid, code, language)
        finally:
            self._release(cid)

    def execute_command(self, command: str) -> str:
        """
        沙盒执行 shell 命令。timeout 默认 120s（可由 SANDBOX_CMD_TIMEOUT 覆盖）。

        与 v1 的区别：同上，不再独占容器。
        """
        cid = self._acquire()
        try:
            return self._exec_command_in_container(cid, command, self.cmd_timeout)
        finally:
            self._release(cid)

    # =========================================================================
    # 内部：单容器内的 exec 实现（锁外，可并发）
    # =========================================================================

    def _execute_in_container(self, cid: str, code: str, language: str) -> str:
        suffix = ".py" if language == "python" else ".js"

        # 检查容器状态（不健康就重建）
        if not self._is_container_running(cid):
            self._logger.debug(f"[SandboxPool] 容器 {cid} 不在跑，重建")
            self._destroy_container(cid)
            new_cid = self._create_container()
            if not new_cid:
                raise RuntimeError(f"无法重建容器（原 {cid}）")
            # 用新 cid 替换（slot 仍归调用方持有）
            self._replace_container(cid, new_cid)
            cid = new_cid

        try:
            # 写入代码到容器根目录：/code.py
            # （不能直接用 docker cp：cp 写入的是镜像 writable layer）
            # 容器以 root 运行，能在 / 下创建/覆盖 /code.py
            write_result = subprocess.run([
                "docker", "exec", "-i", cid,
                "sh", "-c", f"cat > /code{suffix}"
            ], input=code, capture_output=True, text=True, timeout=10)
            if write_result.returncode != 0:
                raise Exception(f"写入容器失败: {write_result.stderr}")

            # 执行代码 + 自动清理 /code.py（无论成功失败都删，避免敏感信息残留）
            # -w / 显式指定 cwd=/，让代码里写 open('cached/xxx') 能解析到 /cached/xxx
            # sh -c 链路：python /code.py → 存 rc → rm -f /code.py → 透传 rc
            result = subprocess.run([
                "docker", "exec", "-w", "/", cid,
                "sh", "-c", f"python /code{suffix}; rc=$?; rm -f /code{suffix}; exit $rc"
            ], capture_output=True, text=True, timeout=self.code_timeout)

            # 重要产出写到 /cached，由 host 文件系统管（mount rw，不随容器清理）
            output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nReturn code: {result.returncode}"
            return output
        finally:
            pass  # release 由调用方负责

    def _exec_command_in_container(self, cid: str, command: str, timeout: int) -> str:
        # 检查容器状态（不健康就重建）
        if not self._is_container_running(cid):
            self._logger.debug(f"[SandboxPool] 容器 {cid} 不在跑，重建")
            self._destroy_container(cid)
            new_cid = self._create_container()
            if not new_cid:
                raise RuntimeError(f"无法重建容器（原 {cid}）")
            self._replace_container(cid, new_cid)
            cid = new_cid

        # sh -c 让管道 / 重定向 / glob 全部走容器内 shell 解析
        # -w / 与 code 路径一致：相对路径 cached/xxx 解析到 /cached/xxx
        result = subprocess.run([
            "docker", "exec", "-w", "/", cid,
            "sh", "-c", command
        ], capture_output=True, text=True, timeout=timeout)

        output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nReturn code: {result.returncode}"
        return output

    def _replace_container(self, old_cid: str, new_cid: str) -> None:
        """把池里的 old_cid 替换为 new_cid，slot 计数不变（在锁内调用）。"""
        with self._pool_lock:
            if old_cid in self.all_containers:
                self.all_containers.discard(old_cid)
                self.idle_containers = deque(
                    new_cid if c == old_cid else c for c in self.idle_containers
                )
            sem = self.container_sems.pop(old_cid, None)
            if sem is not None:
                self.container_sems[new_cid] = sem  # slot 数沿用
            self.temp_containers.discard(old_cid)
            self.last_released_ts.pop(old_cid, None)
            self.all_containers.add(new_cid)
            self.last_released_ts[new_cid] = time.monotonic()

    # =========================================================================
    # 生命周期
    # =========================================================================

    def shutdown(self) -> None:
        """关闭所有容器 + 停 GC 线程。"""
        self._gc_stop.set()
        with self._pool_lock:
            cids = list(self.all_containers)
            self.all_containers.clear()
            self.idle_containers.clear()
            self.container_sems.clear()
            self.temp_containers.clear()
            self.last_released_ts.clear()
        for cid in cids:
            self._destroy_container(cid)
        self._logger.debug(f"[SandboxPool] shutdown 完成,销毁 {len(cids)} 个容器")

    # =========================================================================
    # config 生成（保留原实现）
    # =========================================================================

    def _generate_sandbox_config(self):
        """
        从 host config.json 抽取 skills 段，生成 sandbox-only 配置。

        容器内只需要 skills 的 API key，不需要 llm_providers / oss / app 等其他段。
        生成的文件权限 600，路径 sandbox/.sandbox-config.json（已 .gitignore）。
        """
        try:
            if not os.path.exists(self.config_path):
                self._logger.debug(f"[SandboxPool] config.json 不存在: {self.config_path}，跳过抽取")
                return

            with open(self.config_path, "r", encoding="utf-8") as f:
                full = json.load(f)

            sandbox_cfg = {"skills": full.get("skills", {})}

            os.makedirs(os.path.dirname(self.sandbox_config_path), exist_ok=True)
            with open(self.sandbox_config_path, "w", encoding="utf-8") as f:
                json.dump(sandbox_cfg, f, ensure_ascii=False, indent=2)
            os.chmod(self.sandbox_config_path, 0o600)
            self._logger.debug(f"[SandboxPool] 已生成 sandbox-only config: {self.sandbox_config_path}")
        except Exception as e:
            self._logger.warning(f"[SandboxPool] 生成 sandbox config 失败: {e}")