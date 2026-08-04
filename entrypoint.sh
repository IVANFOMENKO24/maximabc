#!/usr/bin/env bash
set -e

if [ "$(id -u)" = "0" ]; then
  export DEBIAN_FRONTEND=noninteractive
  export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH}"
  if command -v apt-get >/dev/null 2>&1; then
    (apt-get update -y || true) >/tmp/apt-update.log 2>&1 || true
    apt-get install -y --no-install-recommends ffmpeg ca-certificates >/tmp/apt-install.log 2>&1 || true
  elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache ffmpeg ca-certificates >/tmp/apk-install.log 2>&1 || true
  elif command -v dnf >/dev/null 2>&1; then
    dnf -y install ffmpeg >/tmp/dnf-install.log 2>&1 || true
  elif command -v yum >/dev/null 2>&1; then
    yum -y install ffmpeg >/tmp/yum-install.log 2>&1 || true
  fi
fi

exec python -u bot.py "$@"
