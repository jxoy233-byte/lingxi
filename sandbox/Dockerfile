# ChatMe/sandbox/Dockerfile
FROM docker.m.daocloud.io/library/python:3.12-slim

# 安装数据分析 + 图表相关包（使用阿里云镜像）
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
    numpy \
    pandas \
    scipy \
    scikit-learn \
    sympy \
    matplotlib \
    seaborn \
    plotly \
    bokeh \
    altair \
    pygal \
    pyecharts \
    folium \
    networkx \
    requests \
    beautifulsoup4 \
    lxml \
    openpyxl \
    xlrd \
    pillow \
    jinja2 \
    markupsafe

# 创建工作目录
RUN mkdir -p /sandbox && chown -R 1000:1000 /sandbox

WORKDIR /sandbox
USER 1000

CMD ["python"]
