"""解字稿的段落處理：老師寫五段，問事者只收到【解讀】。"""
from __future__ import annotations

import re

AI_MARK = "（AI 草稿，請審閱）"
NO_AI_MARK = "（尚未設定 AI，請老師補充）"
_HEAD = re.compile(r"^【([^】\n]+)】[ \t]*$", re.M)


def split_sections(text: str) -> dict[str, str]:
    heads = list(_HEAD.finditer(text))
    out: dict[str, str] = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out[m.group(1).strip()] = text[m.end():end].strip()
    return out


def public_reading(text: str) -> str:
    """取出要給問事者的【解讀】內容，並去掉「AI 草稿」標記。"""
    body = split_sections(text).get("解讀", "")
    return body.replace(AI_MARK, "").replace(NO_AI_MARK, "").strip()
