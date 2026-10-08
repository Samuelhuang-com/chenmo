"""測試新問字 Email 通知設定。

用法（在 chenmo 資料夾）：
    python scripts/test_email.py
會讀取 .env 的 SMTP 設定，寄一封測試信，並顯示成功或失敗原因。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.models import Case, now_ms  # noqa: E402
from app.services.notify import _send, build_message  # noqa: E402

s = get_settings()
print(f"SMTP 主機  ：{s.smtp_host}:{s.smtp_port}")
print(f"寄件帳號  ：{s.smtp_user or '（未設定 SMTP_USER）'}")
print(f"應用程式密碼：{'已設定，' + str(len(s.smtp_password)) + ' 碼' if s.smtp_password else '（未設定 SMTP_PASSWORD）'}")
print(f"收件人    ：{', '.join(s.notify_recipients) or '（未設定 NOTIFY_EMAILS / MASTER_EMAILS）'}")
if s.smtp_password and len(s.smtp_password) != 16:
    print("⚠ Gmail 應用程式密碼應為 16 碼（不含空白），請確認是否貼錯。")
if not s.email_enabled:
    print("❌ 設定不完整，不會寄信。")
    sys.exit(1)

case = Case(question="這是一封測試信", char="測", char_source="written", stroke_count=12,
            birth_year=75, gender="男", submitted_at=now_ms())
try:
    _send(build_message(case, (s.site_url or "http://127.0.0.1:8080") + "/master"))
except Exception as e:  # noqa: BLE001
    print(f"❌ 寄信失敗：{type(e).__name__}: {e}")
    if "535" in str(e) or "Username and Password" in str(e):
        print("   → 帳號或應用程式密碼錯誤。請到 https://myaccount.google.com/apppasswords 重新產生。")
    sys.exit(1)
print("✅ 已寄出，請到收件匣（或垃圾郵件）查看。")
