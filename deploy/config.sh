# 部署參數：只要改這裡
PROJECT_ID="${PROJECT_ID:-請填你的GCP專案ID}"
REGION="asia-east1"          # 台灣彰化機房
SERVICE="chenmo"
RUN_SA="chenmo-run"          # Cloud Run 執行身分
MASTER_EMAILS="${MASTER_EMAILS:-請填老師的Google信箱}"   # 多位用逗號分隔

if [[ "$PROJECT_ID" == 請填* || "$MASTER_EMAILS" == 請填* ]]; then
  echo "❌ 請先編輯 deploy/config.sh，填入 PROJECT_ID 與 MASTER_EMAILS" >&2
  exit 1
fi
