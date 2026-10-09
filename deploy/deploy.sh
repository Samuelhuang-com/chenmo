#!/usr/bin/env bash
# 部署到 Cloud Run（從原始碼直接建置，不需本機 Docker）
#   bash deploy/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

# 只讓 GitHub Actions 部署，避免從 Cloud Shell / 本機部署把舊版蓋掉新版。
# 真的需要手動部署時：ALLOW_MANUAL_DEPLOY=1 bash deploy/deploy.sh
if [[ "${GITHUB_ACTIONS:-}" != "true" && "${ALLOW_MANUAL_DEPLOY:-}" != "1" ]]; then
  echo "❌ 請用 GitHub Actions 部署（git push 到 main，或在 GitHub 的 Actions 頁按 Run workflow）。" >&2
  echo "   手動部署可能把舊版程式覆蓋掉新版。真的要手動部署，請加上 ALLOW_MANUAL_DEPLOY=1。" >&2
  exit 1
fi
gcloud config set project "$PROJECT_ID" >/dev/null

SECRETS="SECRET_KEY=chenmo-secret-key:latest"
if gcloud secrets describe chenmo-google-client-id >/dev/null 2>&1; then
  SECRETS="$SECRETS,GOOGLE_CLIENT_ID=chenmo-google-client-id:latest,GOOGLE_CLIENT_SECRET=chenmo-google-client-secret:latest"
fi

if gcloud secrets describe chenmo-anthropic-key >/dev/null 2>&1; then
  SECRETS="$SECRETS,ANTHROPIC_API_KEY=chenmo-anthropic-key:latest"
fi

if gcloud secrets describe chenmo-smtp-password >/dev/null 2>&1; then
  SECRETS="$SECRETS,SMTP_PASSWORD=chenmo-smtp-password:latest"
fi

# 信中連結用固定網址（與 Google 登入設定的網址一致）
PROJECT_NUMBER="${PROJECT_NUMBER:-$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)' 2>/dev/null || true)}"
SITE_URL="https://$SERVICE-$PROJECT_NUMBER.$REGION.run.app"

# 版次：這次部署的 commit 訊息（git_push_auto.bat 產生的 fix: YYYYMMDD-NNN）、短 sha、部署時間，顯示在 /master/system
APP_VERSION="$(git log -1 --pretty=%s 2>/dev/null | tr -d ';\r\n' || true)"
APP_COMMIT="$(git rev-parse --short HEAD 2>/dev/null || true)"
APP_DEPLOYED_AT="$(TZ=Asia/Taipei date '+%Y-%m-%d %H:%M')"

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
  --set-env-vars "^;^REPO_BACKEND=firestore;GCP_PROJECT=$PROJECT_ID;SECURE_COOKIES=true;MASTER_EMAILS=$MASTER_EMAILS;SMTP_USER=$SMTP_USER;NOTIFY_EMAILS=$NOTIFY_EMAILS;SITE_URL=$SITE_URL;SPONSOR_LINE_URL=$SPONSOR_LINE_URL;BRAND_LOGO=$BRAND_LOGO;APP_VERSION=$APP_VERSION;APP_COMMIT=$APP_COMMIT;APP_DEPLOYED_AT=$APP_DEPLOYED_AT" \
  --set-secrets "$SECRETS"

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')
echo
echo "✅ 已部署：$URL"
echo "   OAuth「已授權的重新導向 URI」請填：$URL/master/auth/callback"
