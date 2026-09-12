FROM mcr.microsoft.com/devcontainers/python:3.11-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ddddocr / OpenCV 运行时库。Playwright --with-deps 可能间接带上其中一部分，
# 但 import cv2 在干净镜像上仍需要 libGL。
RUN sudo apt-get update \
    && sudo apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && sudo rm -rf /var/lib/apt/lists/*

# 拷贝环境需求
COPY requirements.txt /tmp/pip-tmp/requirements.txt
# sudo 强制全局安装
RUN sudo pip install --upgrade pip \
    && sudo pip install -r /tmp/pip-tmp/requirements.txt \
    && sudo rm -rf /tmp/pip-tmp

# sudo 会丢掉 Dockerfile ENV，必须在命令里重申浏览器目录。
# 将 Chromium 装到共享路径，vscode 用户也可以启动。
RUN sudo mkdir -p /ms-playwright \
    && sudo env PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
        playwright install --with-deps chromium \
    && sudo chmod -R a+rX /ms-playwright
