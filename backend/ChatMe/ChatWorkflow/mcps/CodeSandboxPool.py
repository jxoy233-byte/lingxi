import json
import os
import subprocess
import threading
from pathlib import Path


class SandboxPool:
    def __init__(
        self,
        size=2,
        image="chatme-python-sandbox:latest",
        skills_path=None,    # 可选覆盖，默认按 __file__ 推断 backend/skills
        cached_path=None,    # 可选覆盖，默认按 __file__ 推断 backend/cached
        config_path=None,
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

        self.lock = threading.Lock()
        self.containers = []
        # 预启动容器
        for _ in range(size):
            cid = self._create_container()
            if cid:
                self.containers.append(cid)
        print(
            f"[SandboxPool] 初始化完成，容器数: {len(self.containers)}, "
        )

    def _generate_sandbox_config(self):
        """
        从 host config.json 抽取 skills 段，生成 sandbox-only 配置。

        容器内只需要 skills 的 API key，不需要 llm_providers / oss / app 等其他段。
        生成的文件权限 600，路径 sandbox/.sandbox-config.json（已 .gitignore）。
        """
        try:
            if not os.path.exists(self.config_path):
                print(f"[SandboxPool] config.json 不存在: {self.config_path}，跳过抽取")
                return

            with open(self.config_path, "r", encoding="utf-8") as f:
                full = json.load(f)

            sandbox_cfg = {"skills": full.get("skills", {})}

            os.makedirs(os.path.dirname(self.sandbox_config_path), exist_ok=True)
            with open(self.sandbox_config_path, "w", encoding="utf-8") as f:
                json.dump(sandbox_cfg, f, ensure_ascii=False, indent=2)
            os.chmod(self.sandbox_config_path, 0o600)
            print(f"[SandboxPool] 已生成 sandbox-only config: {self.sandbox_config_path}")
        except Exception as e:
            print(f"[SandboxPool] 生成 sandbox config 失败: {e}")

    def _create_container(self):
        """
        启动一个常驻容器：
        - mount skills(ro) + cached(rw) + sandbox-only config + logs
        - 容器内能看到：/skills, /cached, /.chatme/config.json（仅 skills 段）, /.chatme/logs
        - ChatMeConfig / ChatDataAnalysis 已通过 Dockerfile COPY 进 site-packages
        """
        try:
            self._generate_sandbox_config()

            cmd = [
                "docker", "run", "-d",
                # skills 只读：保护源码 + 让 import skills.* 直接生效
                "-v", f"{self.skills_path}:/skills:ro",
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
            print(f"[SandboxPool] 创建容器: {container_id}")
            return container_id
        except Exception as e:
            print(f"[SandboxPool] 创建容器失败: {e}")
            return None

    def execute(self, code, language="python"):
        """从池中取出容器执行代码"""
        with self.lock:
            if not self.containers:
                raise RuntimeError("No available containers in pool")

            container_id = self.containers.pop()
            suffix = ".py" if language == "python" else ".js"

            # 检查容器状态
            result = subprocess.run(
                ["docker", "inspect", container_id, "--format", "{{.State.Running}}"],
                capture_output=True, text=True
            )
            is_running = result.stdout.strip() == "true"

            if not is_running:
                # 删除并重新创建
                subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
                container_id = self._create_container()
                if not container_id:
                    raise RuntimeError("无法创建新容器")

            try:
                # 写入代码到容器根目录：/code.py
                # （不能直接用 docker cp：cp 写入的是镜像 writable layer）
                # 容器以 root 运行，能在 / 下创建/覆盖 /code.py
                write_result = subprocess.run([
                    "docker", "exec", "-i", container_id,
                    "sh", "-c", f"cat > /code{suffix}"
                ], input=code, capture_output=True, text=True, timeout=10)
                if write_result.returncode != 0:
                    raise Exception(f"写入容器失败: {write_result.stderr}")

                # 执行代码 + 自动清理 /code.py（无论成功失败都删，避免敏感信息残留）
                # -w / 显式指定 cwd=/，让代码里写 open('cached/xxx') 能解析到 /cached/xxx
                # sh -c 链路：python /code.py → 存 rc → rm -f /code.py → 透传 rc
                result = subprocess.run([
                    "docker", "exec", "-w", "/", container_id,
                    "sh", "-c", f"python /code{suffix}; rc=$?; rm -f /code{suffix}; exit $rc"
                ], capture_output=True, text=True, timeout=300)

                # 重要产出写到 /cached，由 host 文件系统管（mount rw，不随容器清理）

                output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nReturn code: {result.returncode}"
                return output
            finally:
                self.containers.append(container_id)

    def execute_command(self, command: str) -> str:
        """从池中取出容器执行 shell 命令

        与 execute(code, language) 的差异：
        - 不写临时文件，直接 docker exec sh -c <command>，命令里可以含管道 / 重定向 / glob
        - cwd=/ 让相对路径（cached/xxx）能解析到 /cached/xxx（与 code 一致语义）
        - 白名单 / 危险检测由调用方（server.py 的 cmd 工具）负责
        - timeout 硬编码 120s
        """
        timeout = 120
        with self.lock:
            if not self.containers:
                raise RuntimeError("No available containers in pool")

            container_id = self.containers.pop()

            # 检查容器状态
            result = subprocess.run(
                ["docker", "inspect", container_id, "--format", "{{.State.Running}}"],
                capture_output=True, text=True
            )
            is_running = result.stdout.strip() == "true"

            if not is_running:
                # 删除并重新创建
                subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
                container_id = self._create_container()
                if not container_id:
                    raise RuntimeError("无法创建新容器")

            try:
                # sh -c 让管道 / 重定向 / glob 全部走容器内 shell 解析
                # -w / 与 code 路径一致：相对路径 cached/xxx 解析到 /cached/xxx
                result = subprocess.run([
                    "docker", "exec", "-w", "/", container_id,
                    "sh", "-c", command
                ], capture_output=True, text=True, timeout=timeout)

                output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nReturn code: {result.returncode}"
                return output
            finally:
                self.containers.append(container_id)

    def shutdown(self):
        """关闭所有容器"""
        for cid in self.containers:
            try:
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=5)
            except Exception:
                pass
        self.containers.clear()