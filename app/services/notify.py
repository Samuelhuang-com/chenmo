"""新問字 Email 通知。

使用 SMTP（預設 Gmail：smtp.gmail.com:587 + 應用程式密碼）。
未設定 SMTP_USER / SMTP_PASSWORD 時自動略過；寄信失敗只記錄，不影響學生送出。
"""
from __future__ import annotations

import asyncio
import logging
import re
import smtplib
from email.message import EmailMessage
from html import escape

from app.config import get_settings
from app.models import Case
from app.templating import fmt_ms

log = logging.getLogger(__name__)


def build_message(case: Case, link: str) -> EmailMessage:
    s = get_settings()
    char = case.char or "（未填）"
    source = "自選字" if case.char_source == "picked" else "手寫"
    who = case.profile_text or "未填年次與性別"
    msg = EmailMessage()
    msg["Subject"] = f"【{s.app_name}】新問字「{char}」— {re.sub(r'（.*?）', '', who)}"
    msg["From"] = f"{s.app_name} <{s.smtp_user}>"
    msg["To"] = ", ".join(s.notify_recipients)

    lines = [
        f"有人在{s.app_name}呈送了問字：",
        "",
        f"所問：{case.question}",
        f"問事者：{who}",
        f"此字：{char}（{source}，{case.stroke_count} 筆）",
    ]
    if case.char_source == "picked" and case.offered:
        lines.append(f"候選字：{'、'.join(case.offered)}")
    lines += [f"呈送時間：{fmt_ms(case.submitted_at)}", "", f"前往解字：{link}"]
    msg.set_content("\n".join(lines))

    rows = "".join(
        f"<tr><td style='color:#6b625a;padding:4px 16px 4px 0;white-space:nowrap'>{k}</td>"
        f"<td style='padding:4px 0'>{escape(v)}</td></tr>"
        for k, v in [("所問", case.question), ("問事者", who),
                     ("此字", f"{char}（{source}，{case.stroke_count} 筆）"),
                     *([("候選字", "、".join(case.offered))] if case.char_source == "picked" and case.offered else []),
                     ("呈送時間", fmt_ms(case.submitted_at))])
    msg.add_alternative(f"""\
<div style="font-family:'Noto Serif TC',serif;background:#ede5d3;color:#1f1b17;padding:24px;max-width:560px">
  <div style="font-size:56px;line-height:1;margin-bottom:12px">{escape(char)}</div>
  <table style="border-collapse:collapse;font-size:15px">{rows}</table>
  <p style="margin-top:24px"><a href="{escape(link)}"
     style="background:#b23a2e;color:#ede5d3;padding:10px 22px;text-decoration:none;letter-spacing:.2em">前往解字</a></p>
</div>""", subtype="html")
    return msg


def _send(msg: EmailMessage) -> None:
    s = get_settings()
    if s.smtp_port == 465:
        with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=8) as smtp:
            smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=8) as smtp:
            smtp.starttls()
            smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)


async def notify_new_case(case: Case, base_url: str) -> bool:
    s = get_settings()
    if not s.email_enabled:
        log.info("new-case email skipped: SMTP_USER/SMTP_PASSWORD/收件人未設定")
        return False
    link = f"{(s.site_url or base_url).rstrip('/')}/master/case/{case.id}"
    try:
        await asyncio.wait_for(asyncio.to_thread(_send, build_message(case, link)), timeout=10)
        log.info("new-case email sent to %s", ", ".join(s.notify_recipients))
        return True
    except Exception:  # noqa: BLE001
        log.exception("new-case email failed")
        return False


def build_student_message(case: Case, link: str) -> EmailMessage:
    s = get_settings()
    char = case.char or ""
    msg = EmailMessage()
    msg["Subject"] = f"【{s.app_name}】老師已完成「{char}」字的解讀"
    msg["From"] = f"{s.app_name} <{s.smtp_user}>"
    msg["To"] = case.owner_email
    name = case.owner_name or "你好"
    msg.set_content("\n".join([
        f"{name}，", "", f"你在{s.app_name}問的「{case.question}」，老師已經解讀好了。",
        "點下面的連結就能看到你寫的字和老師的解讀：", "", link, "",
        "這個連結請自己保存，也可以登入後在「我的問字」找到。"]))
    msg.add_alternative(f"""\
<div style="font-family:'Noto Serif TC',serif;background:#ede5d3;color:#1f1b17;padding:24px;max-width:560px">
  <div style="font-size:56px;line-height:1;margin-bottom:12px">{escape(char)}</div>
  <p>{escape(name)}，</p>
  <p>你在{escape(s.app_name)}問的「{escape(case.question)}」，老師已經解讀好了。<br>點下面的按鈕，就能看到你寫的字和老師的解讀。</p>
  <p style="margin-top:24px"><a href="{escape(link)}"
     style="background:#b23a2e;color:#ede5d3;padding:10px 22px;text-decoration:none;letter-spacing:.2em">查看解讀</a></p>
  <p style="color:#6b625a;font-size:13px;margin-top:24px">按鈕打不開時，請複製這個連結：<br>{escape(link)}<br>也可以登入後在「我的問字」找到。</p>
</div>""", subtype="html")
    return msg


async def notify_student_answered(case: Case, base_url: str) -> tuple[bool, str]:
    """寄信給有登入的問事者（附問事者連結）。回傳（是否寄出, 沒寄出的原因）。"""
    s = get_settings()
    if not case.owner_email:
        return False, "問事者沒有登入，沒有信箱可寄"
    if not (s.smtp_user and s.smtp_password):
        return False, "尚未設定 SMTP，無法寄信"
    link = f"{(s.site_url or base_url).rstrip('/')}/c/{case.token}"
    try:
        await asyncio.wait_for(asyncio.to_thread(_send, build_student_message(case, link)), timeout=10)
        log.info("answer email sent to student %s", case.owner_email)
        return True, ""
    except Exception as e:  # noqa: BLE001
        log.exception("answer email to student failed")
        return False, f"寄信失敗：{type(e).__name__}"
