from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.config import get_settings

TPE = timezone(timedelta(hours=8))

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["settings"] = get_settings()


def fmt_ms(ms: int | None) -> str:
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, TPE).strftime("%Y-%m-%d %H:%M")


templates.env.filters["fmt_ms"] = fmt_ms


# 隨喜贊助 QR 圖：放在 app/static/img/sponsor-qr.png 就會顯示
SPONSOR_QR = Path(__file__).parent / "static" / "img" / "sponsor-qr.png"
templates.env.globals["sponsor_qr"] = lambda: "/static/img/sponsor-qr.png" if SPONSOR_QR.exists() else ""


# 品牌 Logo 路徑（依 BRAND_LOGO 設定）
def brand(file: str = "logo.svg") -> str:
    key = (get_settings().brand_logo or "C").upper()
    if not (Path(__file__).parent / "static" / "brand" / key).is_dir():
        key = "C"
    return f"/static/brand/{key}/{file}"


templates.env.globals["brand"] = brand
