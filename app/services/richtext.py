"""【解讀】的簡易富文字：老師用網頁編輯器寫，伺服器只留白名單內的標籤與樣式，問事者端才能安全顯示。"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

ALLOWED_TAGS = {"p", "div", "br", "b", "strong", "i", "em", "u", "s", "strike", "del", "ul", "ol", "li",
                "span", "font", "h3", "h4"}
VOID = {"br"}
DROP_CONTENT = {"script", "style", "iframe", "object", "embed", "template", "noscript"}

_COLOR = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgba?\(\s*\d{1,3}\s*(,\s*[\d.]+\s*){2,3}\)|[a-zA-Z]{3,20})$")
_SIZE = re.compile(r"^(\d{1,2}(\.\d+)?)(px|pt|em|rem)$")


def _clean_style(style: str) -> str:
    out = []
    for decl in style.split(";"):
        if ":" not in decl:
            continue
        k, v = (x.strip().lower() for x in decl.split(":", 1))
        if k in ("color", "background-color") and _COLOR.match(v):
            out.append(f"{k}:{v}")
        elif k == "text-align" and v in ("left", "center", "right", "justify"):
            out.append(f"{k}:{v}")
        elif k == "font-weight" and v in ("bold", "normal", "600", "700", "800"):
            out.append(f"{k}:{v}")
        elif k == "font-style" and v in ("italic", "normal"):
            out.append(f"{k}:{v}")
        elif k == "text-decoration" and re.fullmatch(r"(underline|line-through|none)( (underline|line-through))?", v):
            out.append(f"{k}:{v}")
        elif k == "font-size" and _SIZE.match(v) and 8 <= float(re.match(r"[\d.]+", v).group()) <= 48 or \
                (k == "font-size" and v in ("x-small", "small", "medium", "large", "x-large", "xx-large")):
            out.append(f"{k}:{v}")
    return ";".join(out)


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in ALLOWED_TAGS:
            return
        a = ""
        for k, v in attrs:
            v = v or ""
            if k == "style":
                s = _clean_style(v)
                if s:
                    a += f' style="{html.escape(s, quote=True)}"'
            elif tag == "font" and k == "color" and _COLOR.match(v):
                a += f' color="{html.escape(v, quote=True)}"'
            elif tag == "font" and k == "size" and v.isdigit() and 1 <= int(v) <= 7:
                a += f' size="{v}"'
        self.out.append(f"<{tag}{a}>")
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in ALLOWED_TAGS or tag in VOID or tag not in self.stack:
            return
        while self.stack:
            t = self.stack.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


def sanitize_html(raw: str) -> str:
    p = _Sanitizer()
    p.feed(raw or "")
    p.close()
    return p.result().strip()


class _ToText(HTMLParser):
    BLOCK = {"p", "div", "li", "h3", "h4", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.lists: list[list] = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")
        elif tag in ("ul", "ol"):
            self.lists.append([tag, 0])
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n")
            if self.lists:
                self.lists[-1][1] += 1
                self.parts.append("・" if self.lists[-1][0] == "ul" else f"{self.lists[-1][1]}. ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("ul", "ol") and self.lists:
            self.lists.pop()
        if tag in self.BLOCK and tag != "li":
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(raw: str) -> str:
    p = _ToText()
    p.feed(raw or "")
    p.close()
    text = "".join(p.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def text_to_html(text: str) -> str:
    """純文字 → 段落 HTML（舊的解讀、AI 草稿用）。"""
    paras = [p for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]
    out = []
    for p in paras:
        p = p.strip()
        head = p.startswith("梅花易數｜")      # 以字起卦的段落：標題 + 內文
        if head:
            p = p[5:]
        out.append(("<h4>梅花易數</h4>" if head else "") + f"<p>{html.escape(p, quote=False).replace(chr(10), '<br>')}</p>")
    return "".join(out)
