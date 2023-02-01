read -p "Clean old database and containers? (input y to continue) > " confirm
if [ "$confirm" = "y" ]; then
    docker compose run --rm yppf bash env/remove_migrations.sh
    docker compose down -v
else
    exit 1
fi
