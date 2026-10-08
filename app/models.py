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
    draft: str = ""                      # 系統帶出的解字草稿（快取，避免重複呼叫 AI）
    draft_char: str = ""

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
                                        "gender", "profile_text",
                                        "status", "stroke_count",
                                        "created_at", "submitted_at", "answered_at", "answer"})


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
    picked: bool = False                 # 是否為自選字
    offered: list[str] = Field(default_factory=list)
    rounds: int = Field(default=1, ge=1, le=999)

    @field_validator("birth_year")
    @classmethod
    def _by(cls, v: int) -> int:
        if not 1 <= v <= roc_year_now():
            raise ValueError(f"年次請填民國 1 到 {roc_year_now()} 年")
        return v

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


class NotesIn(BaseModel):
    body: str = Field(max_length=20000)
