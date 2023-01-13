#!/usr/bin/env bash

cd $( dirname -- "${BASH_SOURCE[0]}" )

# Generate json configuration 
cat ../local_json_template.json | \
    sed 's/\$DATABASE\$/yppf/g' | \
    sed 's/\$USER\$/root/g' | \
    sed 's/\$PASSWORD\$/secret/g' | \
    sed 's/\$HOST\$/mysql/g' > ../local_json.json

docker-compose up -d
docker-compose exec yppf conda run -n yppf python3 manage.py fill_devdb 
