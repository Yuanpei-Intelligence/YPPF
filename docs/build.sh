#!/usr/bin/env bash

cd $( dirname -- "${BASH_SOURCE[0]}" )

# 如果安装本包，则sphinx会尝试先从此处导入
pip3 uninstall importlib-metadata -y

pip3 install sphinx python-docs-theme

# pip3 freeze

sphinx-apidoc -e -d 2 -o source/yppf ../

make html && cd build/ && ls
