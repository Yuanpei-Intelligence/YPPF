# syntax=docker/dockerfile:1

FROM python:3.8-slim-buster
WORKDIR /yppf

COPY requirements.txt requirements.txt

# mirror: https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip3 install -r requirements.txt 
