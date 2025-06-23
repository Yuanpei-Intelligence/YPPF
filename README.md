# YPPF

[![Commits](https://img.shields.io/github/commit-activity/t/Yuanpei-Intelligence/YPPF)](https://github.com/Yuanpei-Intelligence/YPPF/commits)
![Last commit](https://img.shields.io/github/last-commit/Yuanpei-Intelligence/YPPF)
[![Workflow Status](https://img.shields.io/github/actions/workflow/status/Yuanpei-Intelligence/YPPF/basetest.yml)](https://github.com/Yuanpei-Intelligence/YPPF/actions)
![GitHub forks](https://img.shields.io/github/forks/Yuanpei-Intelligence/YPPF)
![Stars](https://img.shields.io/github/stars/Yuanpei-Intelligence/YPPF?style=social)

[简体中文](README.md) | [English](docs/i18n/en/README.md)

## 如何运行

### 环境要求

- [Python 3.10+](https://www.python.org/downloads/)
- [MySQL 8.0+](https://dev.mysql.com/downloads/mysql/)

> 我们提供了搭建好的 [Dev Container 开发环境](#使用-vscode-dev-container-进行开发)，并强烈建议开发者和使用VSCode的初学者使用它。此外，我们也提供了在[本地](#本地环境搭建)进行环境搭建的方法。

### 使用 VSCode Dev Container 进行开发
需要安装 [Docker](https://www.docker.com/) 和 VSCode 的 [devcontainer 扩展](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)。Linux 用户需要额外安装 docker compose。

在 VSCode 中，将主侧栏视图切换至 远程资源管理器-开发容器，打开项目根目录。若 devcontainer 启动正常，可以看到：

```
vscode ➜ /workspace
```

至此，devcontainer 中相当于一个配置好的 Python 环境，并且无需自行配置 MySQL。

### 本地环境搭建

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
    (.env) $ pip install --require-virtualenv -r requirements.txt
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

### 更新和迁移

在**每次**拉取项目代码后（包括初次下载），你都需要迁移数据库，使其与*模型*一致。

1. 更新迁移文件

    ```shell
    python manage.py makemigrations
    ```

    这将在每个具有*模型*的应用的`migrations`文件夹生成一些迁移文件，请不要删除它们。

    > 如果你怀疑某个应用（即文件夹）没有更新迁移文件，可以手动检查并更新它，直到不再变化：
    > 
    > ```shell
    > $ python manage.py makemigrations xxx_app
    > No change detected
    > ```

2. 执行迁移

    ```shell
    python manage.py migrate
    ```

    > 如果迁移失败，数据库将很可能难以恢复，此时最简单的办法是删库重建，执行`scripts/remove_migrations.sh`，并重新进行[更新和迁移](#更新和迁移)。

### 运行

```shell
# http://localhost:8000
python manage.py runserver
# http://localhost
python manage.py runserver 80
python manage.py runserver 0:80
python manage.py runserver 127.0.0.1:80
# http://ip:port
python manage.py runserver ip:port
```

执行任意一种命令以启动，直到你以`Ctrl-C`退出或关闭终端。启动后，便能通过对应网址访问，访问<http://localhost:8000>试试吧~

### 高级功能

- 生产/调试模式

    将`DEBUG`环境变量设置为`true`以开启调试模式。

    调试模式便于使用，除非你打算在生产环境部署本项目，否则请设置为调试模式。

- 管理员

    运行`python manage.py createsuperuser`，根据指示创建管理员账号。

    管理员账号可用于登录后台`/admin`，试着访问<http://localhost:8000/admin>吧。

- 交互式执行（Django终端）

    ```shell
    python manage.py shell
    ```

    安装IPython后使用更便捷：

    ```shell
    pip install ipython --require-virtualenv
    ```

## 常见问题

- 缺少模块，无法运行：`ModuleNotFoundError: 'module_name'`

    可能因为缺少环境依赖，安装对应模块即可:

    ```shell
    pip install module_name --require-virtualenv
    ```

    如果使用`requirement.txt`安装后依然缺少，欢迎提出[issue](https://github.com/Yuanpei-Intelligence/YPPF/issues)。

- 缺少环境变量，无法运行

    通常提示`os.environ`找不到键，本项目的生产模式需要设置环境变量以保证安全，请切换到[调试模式](#高级功能)。

- 无法连接数据库：`django.db.utils.OperationalError: (2003, "Can’t connect to MySQL server on ‘xxx’`

    - 配置错误：检查已经[更新数据库配置](#初始化配置)并正确设置了`config.json`
    - 若`MySQL`未启动，请先启动对应服务。

- Django配置错误：`ImproperlyConfigured`

    配置文件设置有误，请检查对应配置的config文件并修改。

- 缺少字段：`Unknown column 'xx.xxx' in 'field list'`

    未执行迁移或模型变动未检出，请参考[更新和迁移](#更新和迁移)。必要时可以删库重建。

## 加入我们

您可以通过多种方式为本项目做出贡献，例如加入项目组、帮助改进代码或编写文档。即使您对编程一无所知，也能做出有意义的贡献，我们十分欢迎您向我们报告错误或提出改进建议。

### 报告错误和改进建议

若您在使用时遇到错误，或者有设计新功能的想法，请通过[issue](https://github.com/Yuanpei-Intelligence/YPPF/issues)告诉我们。

若您在使用过程中遇到bug，可以详细描述触发错误的场景和操作，最好保证该错误可以复现。

若在运行代码时发生异常，请在报告中包含错误的traceback上下文信息，并尽量添加该文件的链接，以便查找问题。如有可能，提供能复现错误的代码片段是最直观的方法。

在提出任何建议前，我们希望您能查看是否已有类似提议，避免重复讨论。我们鼓励更具体明确的提案，这比泛泛而谈的交流更高效可行。

### 贡献代码

您应该使用`Git`管理代码。fork本仓库，并基于develop分支提交commit，最终提交拉取请求(PR, [pull request](https://github.com/Yuanpei-Intelligence/YPPF/pulls))。你的任何说明信息都应优先使用中文。

你的 PR **必须**满足以下要求，否则将不予受理：

- 标题清晰
- 查找并链接关联issue（如果存在）
- 通过自动化测试：`python manage.py test`
- 为每个新增接口编写文档

若您的 PR [品质良好](#贡献优质的Pull-Request)，我们会保留您的详细提交信息，并欢迎您成为协作者。

#### 贡献优质的Pull Request

好的 PR 在提交历史、代码质量、PR信息三方面都表现优秀，具体来说有以下特征：

- 线性历史：不含merge commit。若与最新的develop分支冲突，请使用`rebase`代替`merge`。
- 原子化提交：每个commit在功能上不可拆分，而非将大量修改堆砌到同一个commit中。
- 不含零碎修改：极小的修改应该被合并至相关commit中，而非单独提交。
- commit信息有意义且易读
- 符合代码规范，如[Google风格指南](https://zh-google-styleguide.readthedocs.io/en/latest/google-python-styleguide/contents/)
- 代码可读性良好，注释和文档数量适宜
- 为新增接口编写测试，并提供导出信息（`__all__`）
- 同步更新环境说明文件和配置文件
- 为影响他人的改动申请 PR [标签](https://github.com/Yuanpei-Intelligence/YPPF/labels)：如删除、模型修改、环境和配置文件修改等。

## 致谢

### 贡献/参与者

感谢所有参与本项目的同学们和朋友们，是大家的帮助让 YPPF 越来越好！

[![Contributors](https://contrib.rocks/image?repo=Yuanpei-Intelligence/YPPF)](https://github.com/Yuanpei-Intelligence/YPPF/graphs/contributors)

如果觉得本项目对你有帮助，帮忙点个 Star 吧 ~
