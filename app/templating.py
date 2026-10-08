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
