#!/bin/bash

# 获取当前目录的绝对路径
cd "$(dirname -- "${BASH_SOURCE[0]}")/.."

# 获取 migrations 文件夹中除了 __init__.py 以外的所有文件
files=$(find ./*/migrations/* ! -name '__init__.py')
if [ -z "$files" ]
then
    echo "没有迁移历史需要删除。"
    exit 0
fi

echo "将要删除以下文件："
echo "$files"
read -p "确定要删除以上迁移历史？删除后当前数据库将无法使用！ [y/N] " -r
if [[ $REPLY =~ ^[Yy]$ ]]
then
    echo "$files" | xargs -d '\n' rm -rf && echo "删除完成。"
else
    echo "取消删除。"
fi
