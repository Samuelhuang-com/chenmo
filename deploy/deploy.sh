#!/usr/bin/env bash
# 部署到 Cloud Run（從原始碼直接建置，不需本機 Docker）
#   bash deploy/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh
gcloud config set project "$PROJECT_ID" >/dev/null

SECRETS="SECRET_KEY=chenmo-secret-key:latest"
if gcloud secrets describe chenmo-google-client-id >/dev/null 2>&1; then
  SECRETS="$SECRETS,GOOGLE_CLIENT_ID=chenmo-google-client-id:latest,GOOGLE_CLIENT_SECRET=chenmo-google-client-secret:latest"
fi

if gcloud secrets describe chenmo-anthropic-key >/dev/null 2>&1; then
  SECRETS="$SECRETS,ANTHROPIC_API_KEY=chenmo-anthropic-key:latest"
fi

# max-instances=1：第一階段即時連線中樞在記憶體內，必須只有一台。
#   流量變大時改用 Redis（Memorystore）再放寬。
# timeout=3600：WebSocket 單次連線上限 60 分鐘，前端會自動重連。
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --service-account "$RUN_SA@$PROJECT_ID.iam.gserviceaccount.com" \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 1 \
  --concurrency 200 \
  --timeout 3600 \
  --session-affinity \
  --cpu 1 --memory 512Mi \
  --set-env-vars "^;^REPO_BACKEND=firestore;GCP_PROJECT=$PROJECT_ID;SECURE_COOKIES=true;MASTER_EMAILS=$MASTER_EMAILS" \
  --set-secrets "$SECRETS"

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')
echo
echo "✅ 已部署：$URL"
echo "   OAuth「已授權的重新導向 URI」請填：$URL/master/auth/callback"
