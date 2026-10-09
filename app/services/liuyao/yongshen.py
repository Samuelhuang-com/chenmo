"""用神預選：依「為誰問」「問事類別」與問事者性別，建議看哪一個六親（或世爻、應爻）。

只是建議，老師可以在工作台改。規則採六爻通行取法：
  自己問財→妻財、問事業→官鬼、問考試→父母（文書），男問感情→妻財、女問感情→官鬼，
  問健康、出行、其他→世爻；為伴侶問→男看妻財、女看官鬼；為朋友問→兄弟；為其他人問→應爻；
  為家人問要看是誰（長輩父母、子女子孫、平輩兄弟），預設父母，請老師確認。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Yongshen:
    liuqin: str = ""          # 父母／兄弟／子孫／妻財／官鬼；空字串表示看世爻或應爻
    special: str = ""         # 世／應
    reason: str = ""
    lines: list[int] = field(default_factory=list)   # 用神所在爻位（主爻在前）
    hidden: bool = False      # 用神不上卦，取伏神

    @property
    def label(self) -> str:
        return self.liuqin or f"{self.special}爻"

    def as_dict(self) -> dict:
        return {"liuqin": self.liuqin, "special": self.special, "reason": self.reason,
                "lines": self.lines, "hidden": self.hidden, "label": self.label}


def suggest_target(asked_for: str, category: str, gender: str) -> tuple[str, str, str]:
    """回傳（六親, 世／應, 理由）。"""
    male = gender == "男"
    if asked_for == "伴侶":
        return ("妻財", "", "為伴侶問：男看妻財") if male else ("官鬼", "", "為伴侶問：女看官鬼")
    if asked_for == "朋友":
        return "兄弟", "", "為朋友問：看兄弟"
    if asked_for == "家人":
        return "父母", "", "為家人問：預設看父母（長輩）；若是子女請改子孫、平輩改兄弟"
    if asked_for == "其他":
        return "", "應", "為其他人問：看應爻"
    by_cat = {
        "財運": ("妻財", "", "問財運：看妻財"),
        "失物": ("妻財", "", "問失物：看妻財"),
        "事業": ("官鬼", "", "問事業、職位：看官鬼"),
        "考試": ("父母", "", "問考試：看父母（文書）；功名可兼看官鬼"),
        "感情": (("妻財", "", "男問感情：看妻財") if male else ("官鬼", "", "女問感情：看官鬼")),
        "健康": ("", "世", "自己問健康：看世爻；官鬼為病"),
        "出行": ("", "世", "自己問出行：看世爻"),
    }
    return by_cat.get(category, ("", "世", "自己問事：看世爻"))


def choose(chart, asked_for: str, category: str, gender: str, override: dict | None = None) -> Yongshen:
    if override and (override.get("liuqin") or override.get("special")):
        q, sp, why = override.get("liuqin", ""), override.get("special", ""), "老師指定"
    else:
        q, sp, why = suggest_target(asked_for, category, gender)
    y = Yongshen(liuqin=q, special=sp, reason=why)
    if sp:
        y.lines = [ln.position for ln in chart.lines if (ln.shi if sp == "世" else ln.ying)]
        return y
    hits = [ln for ln in chart.lines if ln.liuqin == q]
    if not hits:
        y.hidden = True
        y.lines = [ln.position for ln in chart.lines if ln.fu_liuqin == q]
        return y
    # 兩現以上：動爻優先，其次持世或臨應，其餘依爻位
    hits.sort(key=lambda ln: (not ln.moving, not (ln.shi or ln.ying), ln.position))
    y.lines = [ln.position for ln in hits]
    if override and override.get("line") in y.lines:
        y.lines.remove(override["line"])
        y.lines.insert(0, override["line"])
    return y
