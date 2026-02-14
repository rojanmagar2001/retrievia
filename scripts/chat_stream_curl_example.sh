#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
TOKEN="${TOKEN:?TOKEN is required}"
TENANT_ID="${TENANT_ID:?TENANT_ID is required}"
MESSAGE="${MESSAGE:-What does the onboarding playbook require for week one?}"
CONVERSATION_ID="${CONVERSATION_ID:-}"

if [[ -n "$CONVERSATION_ID" ]]; then
  BODY="{\"conversation_id\":\"$CONVERSATION_ID\",\"message\":\"$MESSAGE\"}"
else
  BODY="{\"message\":\"$MESSAGE\"}"
fi

curl -N "$BASE_URL/v1/chat/stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-Id: $TENANT_ID" \
  -H "Accept: text/event-stream" \
  -H "Content-Type: application/json" \
  --data "$BODY"
