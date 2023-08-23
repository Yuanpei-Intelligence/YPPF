FROM mcr.microsoft.com/devcontainers/python:3.11-bullseye
COPY requirements.txt /tmp/pip-tmp/
# Use sudo to force global install
RUN sudo pip install --upgrade pip
RUN sudo pip install -r /tmp/pip-tmp/requirements.txt && rm -rf /tmp/pip-tmp
