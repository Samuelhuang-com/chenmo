#!/usr/bin/env bash
# 把 Google OAuth 用戶端 ID / 密鑰存進 Secret Manager
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh
gcloud config set project "$PROJECT_ID" >/dev/null

read -rp "OAuth 用戶端 ID：" CID
read -rsp "OAuth 用戶端密鑰（輸入時不顯示）：" CSECRET; echo
for pair in "chenmo-google-client-id:$CID" "chenmo-google-client-secret:$CSECRET"; do
  name="${pair%%:*}"; val="${pair#*:}"
  if gcloud secrets describe "$name" >/dev/null 2>&1; then
    printf '%s' "$val" | gcloud secrets versions add "$name" --data-file=-
  else
    printf '%s' "$val" | gcloud secrets create "$name" --data-file=- --replication-policy=automatic
  fi
done
echo "✅ 已儲存。請再執行 bash deploy/deploy.sh"
