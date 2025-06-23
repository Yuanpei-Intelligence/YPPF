# YPPF

[![Commits](https://img.shields.io/github/commit-activity/t/Yuanpei-Intelligence/YPPF)](https://github.com/Yuanpei-Intelligence/YPPF/commits)
![GitHub forks](https://img.shields.io/github/forks/Yuanpei-Intelligence/YPPF)
![Stars](https://img.shields.io/github/stars/Yuanpei-Intelligence/YPPF)
![Last commit](https://img.shields.io/github/last-commit/Yuanpei-Intelligence/YPPF)
[![Workflow Status](https://img.shields.io/github/actions/workflow/status/Yuanpei-Intelligence/YPPF/basetest.yml)](https://github.com/Yuanpei-Intelligence/YPPF/actions)

[简体中文](/README.md) | [English](README.md)

## How to Run

### Environment Requirement

- [Python 3.10+](https://www.python.org/downloads/)
- [MySQL 8.0+](https://dev.mysql.com/downloads/mysql/)

> We provide a [Dev Container development environment](#use-vscode-dev-container-for-development) and strongly recommend developers and beginners using VSCode to use it. In addition, we also provide a method to build the environment [locally](#build-local-environment).

### Use VSCode Dev Container for Development

You need to install [Docker](https://www.docker.com/) and the [devcontainer extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) of VSCode. Linux users need to install docker compose additionally.

In VSCode, switch the main sidebar view to Remote Explorer - Development Container, and open the project root directory. If the devcontainer starts normally, you can see:

```
vscode ➜ /workspace
```

At this point, the devcontainer is equivalent to a configured Python environment, and MySQL does not need to be configured by yourself.

### Build Local Environment

1. Install Python and start the terminal in the project root directory

2. Create a virtual environment

    ```shell
    python -m venv .env
    ```

    .env can be any name, this command will generate the .env folder as a virtual environment, do not rename the folder.

3. Activate the virtual environment

    - Windows

        ```powershell
        > .env\Scripts\activate
        # (.env) appears in the left side indicates successful activation, 
        # verify it by following methods:
        (.env) > where python
        .env\Scripts\python.exe
        (.env) > py -0p # Verification method for installing pylauncher
        Installed Pythons found by py Launcher for Windows
        (venv)         .env\Scripts\python.exe *
        ```
        
    - Linux/macOS 
    
        ```shell
        $ source .env/bin/activate
        # (.env) appears in the left side indicates successful activation, 
        # verify it by following methods:
        (.env) $ which python
        .env/bin/python
        ```

    - VSCode shortcut activation
    
        Make sure the Python environment in the lower right corner is switched to the virtual environment, such as `3.10.x('.env': venv)`, and start the terminal.

4. Install environment dependencies

    ```shell
    (.env) $ pip install --require-virtualenv -r requirements.txt
    ```

### Initialize Configuration

1. Create a database

    ```mysql
    CREATE DATABASE yppf CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
    ```

2. Create a configuration file

    We use `config.json` to manage configuration items. [`config_template.json`](config_template.json) is its complete template, which contains all optional configurations.

    Copy the template and rename it to `config.json`, you can also run `scripts/default_config.sh` in `bash` terminal.

3. Update database configuration

    | Configuration item | Meaning       | Example   |
    | ------------------ | ------------- | --------- |
    | NAME               | Database name | yppf      |
    | USER               | Database user | root      |
    | PASSWORD           | User password | (empty)   |
    | HOST               | Database host | 127.0.0.1 |
    | PORT               | Database port | 3306      |

    Update the database part of the django in the configuration file, see `config.py` file of each application for more configuration items.

### Updating and Migrating

After **pulling** the project code (including the first download), you need to migrate the database to match the *model*.

1. Update migration files

    ```shell
    python manage.py makemigrations
    ```

    This will generate some migration files in the `migrations` folder of each application with *models*. Please do not delete them.

    > If you suspect that an application (i.e. folder) has not updated migration files, you can manually check and update it until it no longer changes:
    > 
    > ```shell
    > $ python manage.py makemigrations xxx_app
    > No change detected
    > ```

2. Execute migration

    ```shell
    python manage.py migrate
    ```

    > If the migration fails, the database will likely be difficult to recover. The easiest way is to delete the database and rebuild it, run `scripts/remove_migrations.sh`, and then perform [updating and migration](#updating-and-migrating).

### Run

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

Execute any of the commands to start, until you exit with `Ctrl-C` or close the terminal. After starting, you can access it through the corresponding URL, try accessing <http://localhost:8000>~

### Advanced Features

- Production/Debug Mode

    Set the `DEBUG` environment variable to `true` to enable debug mode.

    Debug mode is easy to use, so unless you plan to deploy this project in a production environment, please set it to debug mode.

- Administrator

    Run `python manage.py createsuperuser` and follow the prompts to create an administrator account.

    The administrator account can be used to log in to the backend `/admin`, try accessing <http://localhost:8000/admin>.

- Interactive Execution (Django Terminal)

    ```shell
    python manage.py shell
    ```

    Use IPython for more convenience after installation:

    ```shell
    pip install ipython --require-virtualenv
    ```

## Common Issues

- Missing module, unable to run: `ModuleNotFoundError: 'module_name'`

    This may be due to missing environment dependencies. Install the corresponding module:

    ```shell
    pip install module_name --require-virtualenv
    ```

    If the module is still missing after installing via `requirement.txt`, please feel free to submit an [issue](https://github.com/Yuanpei-Intelligence/YPPF/issues).

- Missing environment variables, unable to run

    Usually prompted with `os.environ` cannot find the key. The production mode of this project requires setting environment variables to ensure security. Please switch to [debug mode](#advanced-features).

- Unable to connect to the database: `django.db.utils.OperationalError: (2003, "Can’t connect to MySQL server on ‘xxx’`

    - Configuration error: Check that you have [updated the database configuration](#initialize-configuration) and correctly set `config.json`.
    - If `MySQL` is not running, please start the corresponding service.

- Django configuration error: `ImproperlyConfigured`

    The configuration file is set incorrectly. Please check the corresponding configuration of the config file and modify it.

- Missing field: `Unknown column 'xx.xxx' in 'field list'`

    Migration has not been executed or model changes have not been detected. Please refer to [updating and migration](#updating-and-migrating). If necessary, you can delete the database and rebuild it.

## Join Us

There are many ways to contribute to this project, such as joining the project team, helping to improve the code, or writing documentation. Even if you know nothing about programming, you can still make meaningful contributions. We welcome you to report errors or suggest improvements to us.

### Reporting Errors and Suggesting Improvements

If you encounter an error while using it, or have ideas for designing new features, please let us know through [issue](https://github.com/Yuanpei-Intelligence/YPPF/issues).

If you encounter a bug during use, you can describe the scenario and operation that triggered the error in detail, and it is best to ensure that the error can be reproduced.

If an exception occurs when running the code, please include the traceback context information of the error in the report, and try to add a link to the file to facilitate problem solving. If possible, providing a code snippet that can reproduce the error is the most intuitive method.

Before making any suggestions, we hope you can check whether there are similar proposals to avoid duplicate discussions. We encourage more specific and clear proposals, which are more efficient and feasible than vague communication.

### Contributing Code

You should use `Git` to manage code. Fork this repository and submit a commit based on the develop branch. Finally, submit a pull request (PR) for review. Your explanatory information should be in Chinese.

Your PR **must** meet the following requirements, otherwise it will not be accepted:

- Clear title
- Find and link related issues (if any)
- Pass automated testing: `python manage.py test`
- Write documentation for each new interface

If your PR is of [good quality](#contributing-high-quality-pull-requests), we will keep your detailed submission information and welcome you to become a collaborator.

#### Contributing High-Quality Pull Requests

Good PRs perform well in terms of submission history, code quality, and PR information, specifically:

- Linear history: no merge commit. If it conflicts with the latest develop branch, use `rebase` instead of `merge`.
- Atomic submission: each commit cannot be split in terms of functionality, rather than piling up a large number of modifications in the same commit.
- No fragmented modifications: extremely small modifications should be merged into related commits, rather than submitted separately.
- Meaningful and readable commit messages
- Compliant with code specifications, such as the [Google Style Guide](https://google.github.io/styleguide/pyguide.html)
- Good code readability, appropriate number of comments and documents
- Write tests for new interfaces and provide export information (`__all__`)
- Synchronously update environment description files and configuration files
- Apply [PR tags](https://github.com/Yuanpei-Intelligence/YPPF/labels) for changes that affect others, such as deletion, model modification, environment and configuration file modification, etc.

## Acknowledgments

### Contributors

Thanks to all the students and friends who participated in this project. It is everyone's help that makes YPPF better and better!

[![Contributors](https://contrib.rocks/image?repo=Yuanpei-Intelligence/YPPF)](https://github.com/Yuanpei-Intelligence/YPPF/graphs/contributors)

If you find this project helpful, please help us by clicking on the Star ~
