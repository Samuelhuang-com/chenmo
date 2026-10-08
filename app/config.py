"""應用程式設定：從環境變數 / .env 讀取。"""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "辰墨軒"
    app_tagline: str = "一字問心・龍墨解疑"
    # Logo 款式：A 金印／B 玄底金辰／C 金環龍盤／D 金格朱印／E 金錢圓章（圖檔在 app/static/brand/）
    brand_logo: str = "C"

    # 簽署 session cookie 用，正式環境請放在 Secret Manager
    secret_key: str = "dev-only-change-me"

    # 資料儲存：sqlite（本機，存成檔案）、firestore（Google Cloud）、memory（測試用，重啟即清空）
    repo_backend: str = "sqlite"
    # SQLite 檔案位置；預設放在使用者家目錄，避開 OneDrive 同步造成檔案鎖定
    sqlite_path: str = "~/.chenmo/chenmo.db"
    gcp_project: str | None = None
    firestore_database: str = "(default)"

    # 老師登入：Google 帳號（建議）
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # 允許登入老師端的 Google 信箱，逗號分隔
    master_emails: str = ""

    # 學生（問事者）是否「必須」先用 Google 登入才能問字。預設 false：可不登入直接問字，登入只是為了保存紀錄
    student_login_required: bool = False

    # 隨喜贊助（請老師喝咖啡）：LINE Pay 收款連結；或放一張收款 QR 圖到 app/static/img/sponsor-qr.png
    sponsor_line_url: str | None = "https://lin.ee/Ti0W37K"
    sponsor_text: str = "如果這次解讀對你有幫助，歡迎隨喜請老師喝杯咖啡。完全自由，不影響任何服務。"

    # 老師登入：密碼（本機開發用；正式環境建議留空停用）
    master_password: str | None = None

    # AI 解字草稿（Claude API）。未設定則只帶出字庫資料
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"

    # 新問字 Email 通知（Gmail：SMTP_USER 填信箱，SMTP_PASSWORD 填「應用程式密碼」）
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    # 收件人，逗號分隔；留空則寄給 MASTER_EMAILS
    notify_emails: str = ""
    # 信中連結使用的網址（留空則用目前請求的網址）
    site_url: str | None = None

    # 限制
    question_max_chars: int = 100
    max_strokes: int = 80
    max_points_per_stroke: int = 3000
    cases_per_ip_per_hour: int = 20

    # Cookie 是否只走 HTTPS（Cloud Run 上設 true）
    secure_cookies: bool = False

    @property
    def master_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.master_emails.split(",") if e.strip()}

    @field_validator("smtp_password")
    @classmethod
    def _strip_spaces(cls, v: str | None) -> str | None:
        # Gmail 應用程式密碼顯示為「xxxx xxxx xxxx xxxx」，登入時要去掉空白
        return v.replace(" ", "").strip() if v else v

    @property
    def notify_recipients(self) -> list[str]:
        raw = self.notify_emails or self.master_emails
        return [e.strip() for e in raw.split(",") if e.strip()]

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_user and self.smtp_password and self.notify_recipients)

    @property
    def google_login_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def student_login_effective(self) -> bool:
        return self.student_login_required and self.google_login_enabled


@lru_cache
def get_settings() -> Settings:
    return Settings()
