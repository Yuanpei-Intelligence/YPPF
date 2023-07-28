#!/usr/bin/env bash

DIR=$( dirname -- "${BASH_SOURCE[0]}" )

cat $DIR/../config_template.json | \
    sed 's/\$DATABASE\$/yppf/g' | \
    sed 's/\$USER\$/root/g' | \
    sed 's/\$PASSWORD\$/secret/g' | \
    sed 's/\"\$SCHEDULER_RPC_PORT\$\"/6666/g' | \
    sed 's/\$HOST\$/mysql/g' > $DIR/../config.json
