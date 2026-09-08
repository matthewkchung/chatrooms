#!/usr/bin/env bash
set -e

flask db upgrade
exec gunicorn app:app --bind 0.0.0.0:8000
