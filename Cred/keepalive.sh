#!/usr/bin/env bash
# Keep Cred alive. Intended for cron (outside the Claude harness):
#   */5 * * * * /home/wojtekhalasa/cred/keepalive.sh >> /home/wojtekhalasa/cred/cred.log 2>&1
# If Cred isn't running, (re)start it detached. Idempotent.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

if pgrep -f "$HERE/cred.py" >/dev/null 2>&1; then
	exit 0
fi
echo "$(date '+%F %T')  Cred down — starting"
setsid "$HERE/venv/bin/python" "$HERE/cred.py" >> "$HERE/cred.log" 2>&1 < /dev/null &
disown 2>/dev/null || true
