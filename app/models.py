"""資料模型。"""
from __future__ import annotations

import secrets
import time
import uuid
from enum import Enum

from pydantic import BaseModel, Field, computed_field, field_validator


def now_ms() -> int:
    return int(time.time() * 1000)


def code_point_len(text: str) -> int:
    """以 Unicode code point 計算字數（罕用字、Emoji 都算 1 字）。"""
    return len(text)  # Python str 本來就是以 code point 為單位


class CaseStatus(str, Enum):
    drafting = "drafting"      # 書寫中
    submitted = "submitted"    # 待解
    answered = "answered"      # 已解


class Case(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    token: str = Field(default_factory=lambda: secrets.token_urlsafe(16))
    question: str = ""
    char: str = ""                       # 問事者自填「寫的是哪個字」（選填）
    char_source: str = ""                # written：自己寫／picked：自選字
    offered: list[str] = Field(default_factory=list)   # 自選字時，系統提供的那一組字
    pick_rounds: int = 0                 # 自選字時按了幾次「換一組」後才選定（第幾組）
    owner_email: str = ""                # 問事者登入的 Google 信箱（未登入為空）
    owner_name: str = ""
    birth_year: int | None = None        # 年次（民國年）
    gender: str = ""                     # 男／女
    status: CaseStatus = CaseStatus.drafting
    stroke_count: int = 0
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)
    submitted_at: int | None = None
    answered_at: int | None = None
    answer: str = ""                     # 送給問事者的內容（只有【解讀】）
    answered_by: str = ""
    notes: str = ""                      # 老師的完整解字稿（五段，問事者看不到）
    revision: int = 0                    # 第幾次送出（收回後重送會加 1）
    retracted_at: int | None = None
    reading_draft: str = ""              # 【解讀】編輯器內容（HTML，自動暫存）
    answer_html: str = ""                # 已送出的【解讀】（HTML）；空表示舊的純文字
    reading_edited_at: int | None = None  # 解讀送出後又修改的時間
    draft: str = ""                      # 系統帶出的解字草稿（快取，避免重複呼叫 AI）
    draft_char: str = ""
    rewrite_requested_at: int | None = None   # 老師請問事者重寫的時間
    rewrite_reason: str = ""             # 重寫原因（會顯示給問事者）
    nickname: str = ""                   # 問事者自填的姓氏／暱稱／英文名（老師辨識用）
    show_sponsor: bool = False           # 老師決定是否在此問事者的頁面顯示「請老師喝杯咖啡」
    follow_of: str = ""                  # 追問：指向上一筆案件的 token
    follow_chain: list[dict] = Field(default_factory=list)   # 追問脈絡：[{"question","char"}…]，由舊到新（只存問題與字）
    redo_of: str = ""                    # 重寫時，指向被取代的舊案件 token
    # ---- 六龍問爻 ----
    kind: str = "char"                   # char：問字／yao：問爻
    asked_for: str = ""                  # 為誰問：自己、家人、伴侶、朋友、其他
    category: str = ""                   # 問事類別（選填）
    yao_values: list[int] = Field(default_factory=list)   # 初爻→上爻，6/7/8/9
    yao_source: str = ""                 # online：線上擲／manual：自己的銅錢／mixed
    yao_clears: int = 0                  # 擲到一半清除重來的次數
    cast_at: int | None = None           # 起卦時間（第六爻擲出的時間），排盤依此
    gua: str = ""                        # 卦名摘要，例「澤火革 → 澤山咸」
    yongshen: dict = Field(default_factory=dict)   # 老師選定的用神 {"liuqin","line","set_by"}
    followups: list[str] = Field(default_factory=list)   # 老師確認的 3 個追問（空則用系統預設）
    verify_status: str = ""              # 卦例回饋：應驗／部分應驗／未應驗
    verify_note: str = ""
    verified_at: int | None = None
    derived_yao: dict = Field(default_factory=dict)   # 問字案件「以字起卦」的參考卦

    @computed_field
    @property
    def profile_text(self) -> str:
        """例：民國 75 年次（西元 1986，屬虎）、男"""
        parts = []
        if self.birth_year:
            parts.append(f"民國 {self.birth_year} 年次（{roc_detail(self.birth_year)}）")
        if self.gender:
            parts.append(self.gender)
        return "、".join(parts)

    def public_dict(self) -> dict:
        """給問事者看的欄位（不含 id）。"""
        return self.model_dump(include={"token", "question", "char", "char_source", "birth_year",
                                        "gender", "nickname", "profile_text",
                                        "status", "stroke_count",
                                        "created_at", "submitted_at", "answered_at", "answer",
                                        "rewrite_requested_at", "rewrite_reason", "reading_edited_at",
                                        "answer_html", "kind", "asked_for", "category",
                                        "yao_values", "cast_at", "gua"})


ZODIAC = "鼠牛虎兔龍蛇馬羊猴雞狗豬"
GENDERS = ("男", "女")


def roc_year_now() -> int:
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=8))).year - 1911


def roc_detail(roc: int) -> str:
    """民國年 → 西元年與生肖（依國曆年粗估，農曆年前出生者請老師自行調整）。"""
    ad = roc + 1911
    return f"西元 {ad}，屬{ZODIAC[(ad - 4) % 12]}"


class SubmitIn(BaseModel):
    question: str
    char: str = ""
    birth_year: int
    gender: str
    nickname: str = Field(default="", max_length=30)   # 姓氏／暱稱／英文名（選填，老師辨識用）
    picked: bool = False                 # 是否為自選字
    offered: list[str] = Field(default_factory=list)
    rounds: int = Field(default=1, ge=1, le=999)

    @field_validator("birth_year")
    @classmethod
    def _by(cls, v: int) -> int:
        if not 1 <= v <= roc_year_now():
            raise ValueError(f"年次請填民國 1 到 {roc_year_now()} 年")
        return v

    @field_validator("nickname")
    @classmethod
    def _nn(cls, v: str) -> str:
        return " ".join(v.split())

    @field_validator("gender")
    @classmethod
    def _g(cls, v: str) -> str:
        if v not in GENDERS:
            raise ValueError("請選擇性別")
        return v

    @field_validator("question")
    @classmethod
    def _q(cls, v: str) -> str:
        from app.config import get_settings
        v = v.strip()
        if not v:
            raise ValueError("請簡述您想問的事")
        if code_point_len(v) > get_settings().question_max_chars:
            raise ValueError(f"問題描述請在 {get_settings().question_max_chars} 字以內")
        return v

    @field_validator("char")
    @classmethod
    def _c(cls, v: str) -> str:
        v = v.strip()
        if code_point_len(v) > 1:
            raise ValueError("請只填一個字")
        return v


class RewriteIn(BaseModel):
    reason: str = Field(default="", max_length=200)


class JieziIn(BaseModel):
    char: str = Field(min_length=1, max_length=2)
    refresh: bool = False                # true：忽略快取重新產生

    @field_validator("char")
    @classmethod
    def _one(cls, v: str) -> str:
        v = v.strip()
        if code_point_len(v) != 1:
            raise ValueError("請輸入一個字")
        return v


class AnswerIn(BaseModel):
    body: str = Field(min_length=1, max_length=20000)   # 老師的完整解字稿
    reading_html: str | None = Field(default=None, max_length=40000)   # 【解讀】編輯器的 HTML
    email_student: bool = False          # 送出後是否寄信通知問事者（需問事者有登入）


class SponsorIn(BaseModel):
    show: bool


class NotesIn(BaseModel):
    body: str = Field(max_length=20000)
    reading_html: str | None = Field(default=None, max_length=40000)


ASKED_FOR = ("自己", "家人", "伴侶", "朋友", "其他")
YAO_CATEGORIES = ("財運", "事業", "感情", "健康", "考試", "出行", "失物", "其他")


class YaoStartIn(BaseModel):
    """問爻：開始起卦前填的資料（與問字相同的驗證規則）。"""
    question: str
    birth_year: int
    gender: str
    nickname: str = Field(default="", max_length=30)
    asked_for: str = "自己"
    category: str = ""
    redo_of: str = Field(default="", max_length=64)
    follow_of: str = Field(default="", max_length=64)

    _q = field_validator("question")(SubmitIn._q.__func__)
    _by = field_validator("birth_year")(SubmitIn._by.__func__)
    _g = field_validator("gender")(SubmitIn._g.__func__)
    _nn = field_validator("nickname")(SubmitIn._nn.__func__)

    @field_validator("asked_for")
    @classmethod
    def _af(cls, v: str) -> str:
        if v not in ASKED_FOR:
            raise ValueError("請選擇為誰而問")
        return v

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        return v if v in YAO_CATEGORIES else ""


class TossIn(BaseModel):
    backs: int | None = Field(default=None, ge=0, le=3)   # 手動模式：三枚中有幾個「背」；None = 線上擲
    shake_ms: int = Field(default=0, ge=0, le=600000)
