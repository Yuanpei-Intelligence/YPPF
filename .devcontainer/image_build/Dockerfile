FROM mcr.microsoft.com/devcontainers/python:3.11-bullseye
COPY dev_requirements.txt /tmp/pip-tmp/dev_requirements.txt
# sudo 强制全局安装
RUN sudo pip install --upgrade pip
# 优先使用指定的开发环境，再补齐环境需求
RUN sudo pip install -r /tmp/pip-tmp/dev_requirements.txt \
    && sudo rm -rf /tmp/pip-tmp
