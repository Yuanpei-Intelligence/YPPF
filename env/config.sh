#!/usr/bin/env bash

DIR=$( dirname -- "${BASH_SOURCE[0]}" )
cat $DIR/../local_json_template.json | \
    sed 's/\$DATABASE\$/yppf/g' | \
    sed 's/\$USER\$/root/g' | \
    sed 's/\$PASSWORD\$/secret/g' | \
    sed 's/\$HOST\$/mysql/g' | \
    sed 's/\"use_scheduler\": false/\"use_scheduler\": true/g' > $DIR/../local_json.json