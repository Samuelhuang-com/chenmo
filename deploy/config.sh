# 部署參數：只要改這裡
PROJECT_ID="${PROJECT_ID:-chenmo-511001}"
PROJECT_NUMBER="${PROJECT_NUMBER:-99237960339}"   # 專案編號（Cloud Run 固定網址用）
REGION="asia-east1"          # 台灣彰化機房
SERVICE="chenmo"
RUN_SA="chenmo-run"          # Cloud Run 執行身分
MASTER_EMAILS="${MASTER_EMAILS:-sam2307@gmail.com}"   # 多位用逗號分隔
# 新問字 Email 通知：寄件 Gmail 與收件人（密碼放 Secret Manager：chenmo-smtp-password）
SMTP_USER="${SMTP_USER:-sam2307@gmail.com}"
NOTIFY_EMAILS="${NOTIFY_EMAILS:-$MASTER_EMAILS}"
# 隨喜贊助：LINE Pay 收款連結（留空則只顯示 QR 圖，兩者都沒有就不顯示贊助區塊）
SPONSOR_LINE_URL="${SPONSOR_LINE_URL:-}"

if [[ "$PROJECT_ID" == 請填* || "$MASTER_EMAILS" == 請填* ]]; then
  echo "❌ 請先編輯 deploy/config.sh，填入 PROJECT_ID 與 MASTER_EMAILS" >&2
  exit 1
fi
