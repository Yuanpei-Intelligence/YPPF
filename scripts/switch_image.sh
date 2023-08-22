cd "$(dirname -- "${BASH_SOURCE[0]}")/.."
sed -i 's/image: yuanpei\/profile:dev1.2/image: yuanpei\/profile:1.2/' .devcontainer/docker-compose.yml
