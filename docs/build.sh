#!/usr/bin/env bash

cd $( dirname -- "${BASH_SOURCE[0]}" )

pip3 install sphinx==4.3 python-docs-theme

# pip3 freeze

sphinx-apidoc -e -d 2 -o source/yppf ../

make html

cd build/

ls
