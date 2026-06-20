import subprocess
import tempfile
import os
import threading


class SandboxPool:
    def __init__(self, size=2, image="chatme-python-sandbox:latest"):
        self.image = image
        self.lock = threading.Lock()
        self.containers = []
        # 预启动容器
        for _ in range(size):
            cid = self._create_container()
            if cid:
                self.containers.append(cid)
        print(f"[SandboxPool] 初始化完成，容器数: {len(self.containers)}")

    def _create_container(self):
        """启动一个常驻容器"""
        try:
            result = subprocess.run([
                "docker", "run", "-d",
                "--tmpfs=/tmp:rw,noexec,size=64m",
                "--tmpfs=/sandbox:rw,noexec,size=64m",
                self.image,
                "sleep", "infinity"
            ], capture_output=True, text=True, timeout=10)
            container_id = result.stdout.strip()
            print(f"[SandboxPool] 创建容器: {container_id}")
            return container_id
        except Exception as e:
            print(f"[SandboxPool] 创建容器失败: {e}")
            return None

    def execute(self, code, language="python"):
        """从池中取出容器执行代码"""
        if not self.containers:
            raise RuntimeError("No available containers in pool")

        container_id = self.containers.pop()
        suffix = ".py" if language == "python" else ".js"

        # 调试：检查容器状态
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

        # 写入临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False) as f:
            f.write(code)
            temp_file = f.name

        try:
            with self.lock:
                # 复制代码到容器
                cp_result = subprocess.run([
                    "docker", "cp", temp_file, f"{container_id}:/sandbox/code{suffix}"
                ], capture_output=True, text=True)
                if cp_result.returncode != 0:
                    raise Exception(f"docker cp failed: {cp_result.stderr}")

                # 执行代码
                result = subprocess.run([
                    "docker", "exec", container_id,
                    "python", f"/sandbox/code{suffix}"
                ], capture_output=True, text=True, timeout=30)

                # 清空 /sandbox 目录
                subprocess.run([
                    "docker", "exec", container_id,
                    "sh", "-c", "rm -f /sandbox/*"
                ], capture_output=True)

            output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nReturn code: {result.returncode}"
            return output

        finally:
            try:
                os.unlink(temp_file)
            except Exception:
                pass
            self.containers.append(container_id)

    def shutdown(self):
        """关闭所有容器"""
        for cid in self.containers:
            try:
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=5)
            except Exception:
                pass
        self.containers.clear()
