#!/usr/bin/env bash
# Locate a working docker CLI + socket inside this WSL distro. Prefers the
# normal integrated setup; falls back to Docker Desktop's shared sockets.
set -u
CLI=/mnt/wsl/docker-desktop/cli-tools/usr/bin/docker
command -v docker >/dev/null 2>&1 && CLI=$(command -v docker)

if [ -x "$CLI" ]; then
  # 1) default socket (full integration)
  if "$CLI" version --format '{{.Server.Version}}' >/dev/null 2>&1; then
    echo "OK default $CLI"
    exit 0
  fi
  # 2) shared sockets (integration half-provisioned)
  for s in /mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.proxy.sock \
           /mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.sock; do
    if [ -S "$s" ] && DOCKER_HOST="unix://$s" "$CLI" version --format '{{.Server.Version}}' >/dev/null 2>&1; then
      echo "OK unix://$s $CLI"
      exit 0
    fi
  done
fi
echo "NO_DOCKER"
exit 1
