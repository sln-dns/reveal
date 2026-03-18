#!/usr/bin/env sh
set -eu

COMPOSE_ARGS=""
if [ "${ENABLE_QUICK_TUNNEL:-0}" = "1" ]; then
  COMPOSE_ARGS="--profile tunnel"
fi

docker compose build --pull
docker compose ${COMPOSE_ARGS} up -d --remove-orphans
docker image prune -f
docker builder prune -f --filter "until=168h" >/dev/null 2>&1 || true
docker compose ${COMPOSE_ARGS} ps

if [ "${ENABLE_QUICK_TUNNEL:-0}" = "1" ]; then
  echo "cloudflared Quick Tunnel is enabled via ENABLE_QUICK_TUNNEL=1"
  QUICK_TUNNEL_URL=""
  ATTEMPT=1
  while [ "$ATTEMPT" -le 10 ]; do
    QUICK_TUNNEL_URL="$(
      docker compose logs cloudflared 2>/dev/null \
        | grep -Eo 'https://[A-Za-z0-9.-]+\.trycloudflare\.com' \
        | tail -n 1 || true
    )"
    if [ -n "$QUICK_TUNNEL_URL" ]; then
      break
    fi
    ATTEMPT=$((ATTEMPT + 1))
    sleep 2
  done

  if [ -n "$QUICK_TUNNEL_URL" ]; then
    echo "Quick Tunnel URL: $QUICK_TUNNEL_URL"
  else
    echo "Quick Tunnel URL was not detected automatically yet. Check: docker compose logs cloudflared"
  fi
else
  echo "cloudflared Quick Tunnel is disabled (set ENABLE_QUICK_TUNNEL=1 to enable it)"
fi
