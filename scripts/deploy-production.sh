#!/usr/bin/env sh
# Deploy one immutable Git commit after GitHub Actions has passed its checks.
set -eu

commit=${1:?Pass the Git commit SHA to deploy}
case "$commit" in
  *[!0-9a-f]*|'') echo "Invalid commit SHA" >&2; exit 2 ;;
esac

git fetch --depth=1 origin "$commit"
git checkout --detach "$commit"
docker compose up -d --build --remove-orphans

attempt=1
while [ "$attempt" -le 12 ]; do
  if curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8080/api/health >/dev/null; then
    docker compose ps
    printf 'H-Point deployed: %s\n' "$commit"
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 5
done

docker compose ps >&2 || true
docker compose logs --tail=100 app bot caddy >&2 || true
exit 1
