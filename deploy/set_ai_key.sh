#!/usr/bin/env bash
# 把 Claude API Key 存進 Secret Manager（AI 解字草稿用）
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh
gcloud config set project "$PROJECT_ID" >/dev/null
read -rsp "Anthropic API Key（輸入時不顯示）：" KEY; echo
if gcloud secrets describe chenmo-anthropic-key >/dev/null 2>&1; then
  printf '%s' "$KEY" | gcloud secrets versions add chenmo-anthropic-key --data-file=-
else
  printf '%s' "$KEY" | gcloud secrets create chenmo-anthropic-key --data-file=- --replication-policy=automatic
fi
echo "✅ 已儲存。請再執行 bash deploy/deploy.sh"
