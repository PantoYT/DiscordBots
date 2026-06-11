#!/usr/bin/env bash
# Launch Cred using its own venv. Run OUTSIDE the Claude Bash-tool harness
# (the harness reaps long-lived processes); the keepalive cron does this.
cd "$(dirname "$0")"
exec ./venv/bin/python cred.py
