#!/usr/bin/env bash

cd $( dirname -- "${BASH_SOURCE[0]}" )

# Generate json configuration 
bash config.sh

# Clear old database related items
if ! bash clean.sh ; then
    exit 1
fi

# Start containers
docker compose up -d

# Fill db with fake records
docker compose exec yppf python3 manage.py fill_devdb 
