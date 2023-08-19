# YPPF

[![Commits](https://img.shields.io/github/commit-activity/t/Yuanpei-Intelligence/YPPF)](https://github.com/Yuanpei-Intelligence/YPPF/commits)
![GitHub forks](https://img.shields.io/github/forks/Yuanpei-Intelligence/YPPF)
![Stars](https://img.shields.io/github/stars/Yuanpei-Intelligence/YPPF)
![Last commit](https://img.shields.io/github/last-commit/Yuanpei-Intelligence/YPPF)
[![Workflow Status](https://img.shields.io/github/actions/workflow/status/Yuanpei-Intelligence/YPPF/basetest.yml)](https://github.com/Yuanpei-Intelligence/YPPF/actions)

[简体中文](README.md) | [English](README_en.md)

## Environment Requirement

- [Python 3.10+](https://www.python.org/downloads/)
- [MySQL 8.0+](https://dev.mysql.com/downloads/mysql/)

> We provide a [Docker development environment](#run-it-with-docker) and recommend using it for development.

## Run it with Docker

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
