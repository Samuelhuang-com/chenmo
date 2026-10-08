"""測試環境設定：一律覆蓋，不受本機 .env 影響（環境變數優先於 .env）。"""
import os

os.environ.update({
    "REPO_BACKEND": "memory",
    "MASTER_PASSWORD": "test-pw",
    "MASTER_EMAILS": "",
    "GOOGLE_CLIENT_ID": "",
    "GOOGLE_CLIENT_SECRET": "",
    "STUDENT_LOGIN_REQUIRED": "false",
    "ANTHROPIC_API_KEY": "",          # 測試不呼叫真的 AI
    "SMTP_USER": "",
    "SMTP_PASSWORD": "",              # 測試不寄真信
    "NOTIFY_EMAILS": "",
    "SITE_URL": "",
    "SPONSOR_LINE_URL": "",
    "SECURE_COOKIES": "false",
    "CASES_PER_IP_PER_HOUR": "1000",  # 測試會建立很多案件
})
