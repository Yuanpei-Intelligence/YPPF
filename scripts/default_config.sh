#!/usr/bin/env bash

DIR=$(dirname "${BASH_SOURCE[0]}")
BASE=$(cd "$DIR"/.. && pwd)

# 如果已经存在 config.json 文件，则判断是否需要覆盖
if [ -f $BASE/config.json ]
then
    read -p "当前目录下已存在 config.json 文件，是否覆盖？[y/N] " -r
    if [[ $REPLY =~ ^[Yy]$ ]]
    then
        echo "覆盖 config.json 文件。"
    else
        echo "取消覆盖。"
        exit 0
    fi
fi

# 读取并复制模板文件
cp $BASE/config_template.json $BASE/config.json

# 替换默认设置
sed -i 's/\$DATABASE\$/yppf/g' $BASE/config.json
sed -i 's/\$USER\$/root/g' $BASE/config.json
sed -i 's/\$PASSWORD\$/secret/g' $BASE/config.json
sed -i 's/\"\$SCHEDULER_RPC_PORT\$\"/6666/g' $BASE/config.json
sed -i 's/\$HOST\$/mysql/g' $BASE/config.json
