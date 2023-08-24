# YPPF

[![Commits](https://img.shields.io/github/commit-activity/t/Yuanpei-Intelligence/YPPF)](https://github.com/Yuanpei-Intelligence/YPPF/commits)
![Last commit](https://img.shields.io/github/last-commit/Yuanpei-Intelligence/YPPF)
[![Workflow Status](https://img.shields.io/github/actions/workflow/status/Yuanpei-Intelligence/YPPF/basetest.yml)](https://github.com/Yuanpei-Intelligence/YPPF/actions)
![GitHub forks](https://img.shields.io/github/forks/Yuanpei-Intelligence/YPPF)
![Stars](https://img.shields.io/github/stars/Yuanpei-Intelligence/YPPF?style=social)

[简体中文](README.md) | [English](README_en.md)

## 如何运行

### 环境要求

- [Python 3.10+](https://www.python.org/downloads/)
- [MySQL 8.0+](https://dev.mysql.com/downloads/mysql/)

> 我们提供了搭建好的 [Docker 开发环境](#启动-docker-容器)，并建议**开发者**使用它。

### 环境搭建

1. 安装Python，在项目根目录启动终端

2. 创建虚拟环境

    ```shell
    python -m venv .env
    ```

    其中.env可以是任何名称，该命令将生成.env文件夹作为虚拟环境，请勿重命名该文件夹。

3. 激活虚拟环境

    - Windows

         ```powershell
         > .env\Scripts\activate
         # 左侧出现(.env)表明成功激活，可通过以下方式检验
         (.env) > where python
         .env\Scripts\python.exe
         (.env) > py -0p # 安装pylauncher的检验方式
         Installed Pythons found by py Launcher for Windows
         (venv)         .env\Scripts\python.exe *
         ```
         
    - Linux/macOS 
    
         ```shell
         $ source .env/bin/activate
         # 左侧出现(.env)表明成功激活，可通过以下方式检验
         (.env) $ which python
         .env/bin/python
         ```
         
    - VSCode快捷激活
    
         确认右下角Python环境切换到虚拟环境，如`3.10.x('.env': venv)`，并启动终端
    
4. 安装环境依赖

    ```shell
    pip install --require-virtualenv -r requirements.txt
    ```

### 初始化配置

1. 创建数据库

    ```mysql
    CREATE DATABASE yppf CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
    ```

2. 创建配置文件

    我们使用`config.json`管理配置项。[`config_template.json`](config_template.json)是其完整模板，包含所有可选配置。

    复制模板并重命名为`config.json`，在`bash`终端中，你也可以运行`scripts/default_config.sh`。

3. 更新数据库配置

    | 配置项   | 含义       | 示例      |
    | -------- | ---------- | --------- |
    | NAME     | 数据库名称 | yppf      |
    | USER     | 数据库用户 | root      |
    | PASSWORD | 用户密码   | （空）    |
    | HOST     | 数据库主机 | 127.0.0.1 |
    | PORT     | 数据库端口 | 3306      |

    更新配置文件中django的数据库部分，更多配置项请参考各应用的`config.py`文件。

## 加入我们

### 启动 Docker 容器

It is recommended to run it with [docker](https://www.docker.com/),
docker-compose and vscode devcontainer.

Within the devcontainer, run the following code to start!

```bash
bash scripts/default_config.sh
python3 manage.py makemigrations # Add new app here if necessary
python3 manage.py migrate
python3 manage.py fill_devdb
python3 manage.py runserver
```

Then, you can access the website from "http://localhost:8000".

Inspect code in *dm/management/fake_records.py* for accounts info.

If you want to test with scheduler job,
edit the config file and change `use_scheduler` to `true`.
Then, open a new terminal and start the scheduler:

```bash
python3 manage.py runscheduler
```




## Project Structure
TODO

## Contribute
Fork the repo, modify on develop branch of your replica.

Reference 

Before open a pull request, run `python3 manage.py test` to check whether your
modification affects other functionality.

### 贡献/参与者

感谢所有参与本项目的同学们和朋友们，是大家的帮助让 YPPF 越来越好！

[![Contributors](https://contrib.rocks/image?repo=Yuanpei-Intelligence/YPPF)](https://github.com/Yuanpei-Intelligence/YPPF/graphs/contributors)

如果觉得本项目对你有帮助，帮忙点个 Star 吧 ~
