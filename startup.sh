#!/usr/bin/env bash
set -e

python -m flask db upgrade

exec python -m gunicorn app:app --bind 0.0.0.0:8000
