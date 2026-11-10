#!/usr/bin/env bash
# Trigger a Grok Bot routine via its webhook.
# Usage: ./send.sh '{"message":"hello"}'   (JSON body is optional)
# Reads GROKBOT_WEBHOOK_URL and GROKBOT_WEBHOOK_KEY from .env next to this script.
# Never prints the key.
set -euo pipefail
cd "$(dirname "$0")/.."  # repo root, where .env lives

set -a; source .env; set +a
: "${GROKBOT_WEBHOOK_URL:?missing in .env}"
: "${GROKBOT_WEBHOOK_KEY:?missing in .env}"

body="${1:-}"
args=(-sS -X POST "$GROKBOT_WEBHOOK_URL"
      -H @- -w '\n--- HTTP %{http_code} in %{time_total}s\n')
if [[ -n "$body" ]]; then
  args+=(-H 'Content-Type: application/json' --data-binary "$body")
fi

# Pass the Authorization header via stdin so the key never appears in the process list.
printf 'Authorization: Bearer %s\n' "$GROKBOT_WEBHOOK_KEY" | curl "${args[@]}"
