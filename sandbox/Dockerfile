# ChatMe/sandbox/Dockerfile
FROM docker.m.daocloud.io/library/python:3.12-slim

# 全局关闭pip自动清理，并发下载
ENV PIP_PARALLEL=6

# 显式声明 HOME=/，Path.home()
ENV HOME=/

# 清理 /skills 和 /cached 根目录下的无用的系统垃圾; python 执行脚本时自动过滤
COPY sandbox/sitecustomize.py /usr/local/lib/python3.12/site-packages/sitecustomize.py

# 安装技能依赖: ChatMeConfig,ChatDataAnalysis,LoggingManager
COPY backend/ChatMe/__init__.py /usr/local/lib/python3.12/site-packages/ChatMe/__init__.py
COPY backend/ChatMe/ChatMeConfig /usr/local/lib/python3.12/site-packages/ChatMe/ChatMeConfig
COPY backend/ChatMe/ChatDataAnalysis /usr/local/lib/python3.12/site-packages/ChatMe/ChatDataAnalysis
COPY backend/ChatMe/LoggingManager /usr/local/lib/python3.12/site-packages/ChatMe/LoggingManager

COPY sandbox/requirements.txt .

RUN python -m pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ \
    &&  pip install --no-build-isolation --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# 创建工作目录
RUN mkdir -p /sandbox /.chatme && chown -R 1000:1000 /sandbox /.chatme

WORKDIR /sandbox
USER 1000

CMD ["python"]
