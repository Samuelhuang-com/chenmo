#!/usr/bin/env bash
# 一次性初始化（在 Google Cloud Console 右上角開啟 Cloud Shell 執行）
#   bash deploy/gcp_setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

echo "▶ 專案：$PROJECT_ID　區域：$REGION"
gcloud config set project "$PROJECT_ID"

echo "▶ 啟用 API"
gcloud services enable \
  run.googleapis.com firestore.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com secretmanager.googleapis.com iamcredentials.googleapis.com

echo "▶ 建立 Firestore（原生模式，台灣）"
if ! gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  gcloud firestore databases create --location="$REGION" --type=firestore-native
else
  echo "  已存在，略過"
fi

echo "▶ 建立 Firestore 複合索引（看板與已解紀錄用，建立約需數分鐘）"
for spec in "answered_at" "created_at"; do
  gcloud firestore indexes composite create --collection-group=cases \
    --field-config=field-path=status,order=ascending \
    --field-config=field-path=$spec,order=descending --async 2>/dev/null || echo "  索引 status+$spec 已存在，略過"
done

echo "▶ 建立 Cloud Run 執行服務帳號"
SA_EMAIL="$RUN_SA@$PROJECT_ID.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$RUN_SA" --display-name="辰墨軒 Cloud Run"
for role in roles/datastore.user roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" --role="$role" --condition=None >/dev/null
done

echo "▶ 建立 session 簽章金鑰（Secret Manager）"
if ! gcloud secrets describe chenmo-secret-key >/dev/null 2>&1; then
  python3 -c "import secrets;print(secrets.token_urlsafe(48),end='')" | \
    gcloud secrets create chenmo-secret-key --data-file=- --replication-policy=automatic
fi

cat <<MSG

✅ 初始化完成。下一步：
  1. 先執行一次部署取得網址：      bash deploy/deploy.sh
  2. 到 Console 建立 OAuth 用戶端（見 docs/GCP部署指南.md 第 4 節），
     再把用戶端 ID / 密鑰存進 Secret Manager：
       bash deploy/set_oauth.sh
  3. 再部署一次即可啟用 Google 登入： bash deploy/deploy.sh
MSG
