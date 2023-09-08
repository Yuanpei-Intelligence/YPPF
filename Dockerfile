FROM mcr.microsoft.com/devcontainers/python:3.11-bullseye
# 拷贝环境需求
COPY requirements.txt /tmp/pip-tmp/requirements.txt
# sudo 强制全局安装
RUN sudo pip install --upgrade pip
RUN sudo pip install -r /tmp/pip-tmp/requirements.txt \
    && sudo rm -rf /tmp/pip-tmp
