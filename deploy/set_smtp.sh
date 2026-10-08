#!/usr/bin/env bash
# 把 Gmail「應用程式密碼」存進 Secret Manager（新問字 Email 通知用）
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh
gcloud config set project "$PROJECT_ID" >/dev/null
read -rsp "Gmail 應用程式密碼（16 碼，輸入時不顯示）：" PW; echo
PW="${PW// /}"   # 去掉空白
if gcloud secrets describe chenmo-smtp-password >/dev/null 2>&1; then
  printf '%s' "$PW" | gcloud secrets versions add chenmo-smtp-password --data-file=-
else
  printf '%s' "$PW" | gcloud secrets create chenmo-smtp-password --data-file=- --replication-policy=automatic
fi
echo "✅ 已儲存。請再部署一次（git push 或 bash deploy/deploy.sh）"
