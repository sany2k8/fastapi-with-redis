#!/usr/bin/env bash
# Start the API from the project directory regardless of where it is invoked from.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run uvicorn app.main:app --reload --port 8800
