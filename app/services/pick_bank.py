"""自選字的「主題字庫」：讓一組 20 字彼此有關聯，而不是 20 個不相干的字。

結構：主題（12 個）→ 子題（階段配額）→ 字。資料在 app/data/pick/：
  themes.json            12 大主題；沒有子題的主題退回「平鋪字池」（該主題的 20 字）
  groups.json            子題：階段、配額、候選字（同一子題內各階段候選字不得重疊）
  character_meanings.json  單字寓意

設計重點
- 無狀態：「換一組」由前端把上一組字以 exclude 傳入，伺服器不記憶任何狀態（Cloud Run 多實例也正確）。
- 各階段候選字互不重疊，所以各階段獨立抽樣就必然得到 20 個不重複字。
- 字庫壞掉時由呼叫端（pick.py）退回原本的 pick_pool.txt 隨機抽字，不影響問字。
- 老師可編輯 JSON；變更前請執行 `python scripts/validate_pick_bank.py`，測試也會自動檢查。
"""
from __future__ import annotations

import json
import random
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "pick"

# 預言式用語：字義文字不應出現（只作書寫與自我反思的參考）
FORBIDDEN_WORDS = ("必定", "一定會", "註定", "保證", "必然", "命中", "災", "厄", "劫")


class BankError(Exception):
    """字庫設定錯誤。"""


def is_single_han(s: str) -> bool:
    """單一完整漢字（以 Unicode 碼位判斷）。"""
    if len(s) != 1:
        return False
    cp = ord(s)
    return (
        0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0x20000 <= cp <= 0x2A6DF or 0xF900 <= cp <= 0xFAFF
    ) and unicodedata.category(s) == "Lo"


def _uniq(s: str) -> list[str]:
    seen, out = set(), []
    for ch in s:
        if ch not in seen:
            seen.add(ch)
            out.append(ch)
    return out


# --------------------------------------------------------------------------- 驗證
def validate_data(themes: dict, groups: dict, meanings: dict) -> tuple[list[str], list[str]]:
    """回傳 (errors, warnings)。errors 非空就不應上線。"""
    errors: list[str] = []
    warnings: list[str] = []
    theme_list = themes.get("themes", [])
    group_list = groups.get("groups", [])
    mean_map = meanings.get("characters", {})

    theme_ids = [t.get("id") for t in theme_list]
    group_ids = [g.get("id") for g in group_list]
    for label, ids in (("theme", theme_ids), ("group", group_ids)):
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            errors.append(f"{label} id 重複：{sorted(dup)}")
        if any(not i for i in ids):
            errors.append(f"{label} 缺少 id")

    used: set[str] = set()
    group_by_id = {g["id"]: g for g in group_list if g.get("id")}

    for t in theme_list:
        tid = t.get("id")
        for key in ("name", "short", "prompt", "pool"):
            if not t.get(key):
                errors.append(f"主題 {tid} 缺少欄位 {key}")
        pool = t.get("pool", "")
        if len(pool) != len(set(pool)):
            errors.append(f"主題 {tid} 的 pool 有重複字")
        for ch in pool:
            if not is_single_han(ch):
                errors.append(f"主題 {tid} 的 pool 含非漢字：{ch!r}")
        if len(pool) < 20:
            warnings.append(f"主題 {tid} 的 pool 少於 20 字（{len(pool)}）")
        used.update(pool)
        for gid in t.get("group_ids", []):
            g = group_by_id.get(gid)
            if g is None:
                errors.append(f"主題 {tid} 指到不存在的子題 {gid}")
            elif g.get("theme_id") != tid:
                errors.append(f"子題 {gid} 的 theme_id 與主題 {tid} 不一致")

    for g in group_list:
        gid = g.get("id")
        if g.get("theme_id") not in theme_ids:
            errors.append(f"子題 {gid} 的 theme_id 無效：{g.get('theme_id')}")
        else:
            owner = next(t for t in theme_list if t["id"] == g["theme_id"])
            if gid not in owner.get("group_ids", []):
                errors.append(f"子題 {gid} 未列在主題 {g['theme_id']} 的 group_ids")
        for key in ("name", "tagline", "summary", "prompt"):
            if not g.get(key):
                errors.append(f"子題 {gid} 缺少欄位 {key}")
        size, stages = g.get("sample_size"), g.get("stages", [])
        if not isinstance(size, int) or size <= 0:
            errors.append(f"子題 {gid} 的 sample_size 無效")
            continue
        if not stages:
            errors.append(f"子題 {gid} 沒有階段")
            continue
        quota_sum, seen_in_group = 0, {}
        for st in stages:
            sname, q, chars = st.get("name", "?"), st.get("quota"), st.get("characters", "")
            if not isinstance(q, int) or q <= 0:
                errors.append(f"子題 {gid}／{sname} 的 quota 必須是正整數")
                continue
            quota_sum += q
            if len(chars) != len(set(chars)):
                errors.append(f"子題 {gid}／{sname} 的候選字有重複")
            for ch in chars:
                if not is_single_han(ch):
                    errors.append(f"子題 {gid}／{sname} 含非漢字：{ch!r}")
                if ch in seen_in_group and seen_in_group[ch] != sname:
                    errors.append(f"子題 {gid} 的「{ch}」同時出現在「{seen_in_group[ch]}」與「{sname}」（階段候選字不得重疊）")
                seen_in_group.setdefault(ch, sname)
            used.update(chars)
            n = len(set(chars))
            if n < q:
                errors.append(f"子題 {gid}／{sname} 候選字（{n}）少於配額（{q}）")
            elif n == q:
                warnings.append(f"子題 {gid}／{sname} 候選字剛好等於配額，此階段無法換一組變化")
            elif n < 2 * q:
                warnings.append(f"子題 {gid}／{sname} 候選字少於配額 2 倍，換一組的變化有限")
        if quota_sum != size:
            errors.append(f"子題 {gid} 的配額加總（{quota_sum}）不等於 sample_size（{size}）")

    for ch in sorted(used):
        info = mean_map.get(ch)
        if not info:
            errors.append(f"缺少字義：{ch}")
            continue
        m = info.get("meaning", "")
        if not m:
            errors.append(f"字義為空：{ch}")
        elif len(m) > 24:
            warnings.append(f"字義過長（{len(m)} 字）：{ch}")
        if any(w in m for w in FORBIDDEN_WORDS):
            errors.append(f"字義含預言式用語：{ch}「{m}」")
        if not info.get("keywords"):
            warnings.append(f"字 {ch} 沒有關鍵詞")
    for ch in mean_map:
        if not is_single_han(ch):
            errors.append(f"字義檔的 key 不是單一漢字：{ch!r}")
        elif ch not in used:
            warnings.append(f"字義檔中的「{ch}」尚未被任何主題或子題使用")
    return errors, warnings


# --------------------------------------------------------------------------- 字庫
@dataclass
class CharacterBank:
    themes: dict
    groups: dict
    meanings: dict
    theme_by_id: dict = field(init=False)
    group_by_id: dict = field(init=False)
    version: str = field(init=False)

    def __post_init__(self) -> None:
        self.theme_by_id = {t["id"]: t for t in self.themes["themes"]}
        self.group_by_id = {g["id"]: g for g in self.groups["groups"]}
        self.version = f"{self.themes.get('version', '?')}/{self.groups.get('version', '?')}/{self.meanings.get('version', '?')}"

    @classmethod
    def load(cls, data_dir: Path | str = DATA_DIR, *, strict: bool = True) -> "CharacterBank":
        d = Path(data_dir)
        try:
            themes = json.loads((d / "themes.json").read_text(encoding="utf-8"))
            groups = json.loads((d / "groups.json").read_text(encoding="utf-8"))
            meanings = json.loads((d / "character_meanings.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise BankError(f"讀取字庫失敗：{e}") from e
        errors, _ = validate_data(themes, groups, meanings)
        if errors and strict:
            raise BankError("字庫驗證失敗：\n- " + "\n- ".join(errors[:20]))
        return cls(themes, groups, meanings)

    # ----- 查詢
    def list_themes(self) -> list[dict]:
        return [{"id": t["id"], "name": t["name"], "short": t["short"],
                 "description": t.get("description", ""), "has_groups": bool(t.get("group_ids"))}
                for t in self.themes["themes"]]

    def all_chars(self) -> frozenset[str]:
        """字庫中出現過的所有字（用來驗證前端回傳的候選字）。"""
        out: set[str] = set()
        for t in self.themes["themes"]:
            out.update(t["pool"])
        for g in self.groups["groups"]:
            for st in g["stages"]:
                out.update(st["characters"])
        return frozenset(out)

    def label(self, theme_id: str, group_id: Optional[str] = None) -> str:
        """給老師看的方向名稱；代號不正確時回傳空字串（不讓前端亂寫文字進紀錄）。"""
        t = self.theme_by_id.get(theme_id or "")
        if t is None:
            return ""
        if group_id and group_id in t.get("group_ids", []):
            return self.group_by_id[group_id]["name"]
        return t["short"]

    def _meanings_for(self, chars: Iterable[str]) -> dict:
        m = self.meanings["characters"]
        return {c: m[c] for c in chars if c in m}

    # ----- 抽字
    def pick(self, theme_id: str, group_id: Optional[str] = None, exclude: str = "",
             rng: Optional[random.Random] = None) -> dict:
        """為指定主題產生一組字。exclude：上一組的字，候選足夠時優先抽沒出現過的字。"""
        rng = rng or random.SystemRandom()
        theme = self.theme_by_id.get(theme_id)
        if theme is None:
            raise KeyError(f"找不到主題：{theme_id}")
        ex = set(exclude)
        gids = theme.get("group_ids", [])
        if group_id:
            if group_id not in gids:
                raise KeyError(f"主題 {theme_id} 沒有子題 {group_id}")
            gid: Optional[str] = group_id
        else:
            gid = rng.choice(gids) if gids else None
        if gid is None:
            return self._pick_pool(theme, ex, rng)
        return self._pick_group(theme, self.group_by_id[gid], ex, rng)

    def _pick_group(self, theme: dict, group: dict, ex: set, rng: random.Random) -> dict:
        stages_out, can_redraw = [], False
        for st in group["stages"]:
            cands, q = _uniq(st["characters"]), st["quota"]
            if len(cands) > q:
                can_redraw = True
            fresh = [c for c in cands if c not in ex]
            stale = [c for c in cands if c in ex]
            rng.shuffle(fresh)
            rng.shuffle(stale)
            chosen = (fresh + stale)[:q]
            rng.shuffle(chosen)
            stages_out.append({"name": st["name"], "hint": st.get("hint", ""), "characters": chosen})
        all_chars = [c for s in stages_out for c in s["characters"]]
        assert len(all_chars) == len(set(all_chars)) == group["sample_size"], "抽字結果不是 20 個不重複字"
        return {
            "source": "group", "theme_id": theme["id"], "theme_name": theme["name"],
            "group_id": group["id"], "group_name": group["name"], "tagline": group["tagline"],
            "can_redraw": can_redraw, "stages": stages_out, "meanings": self._meanings_for(all_chars),
        }

    def _pick_pool(self, theme: dict, ex: set, rng: random.Random) -> dict:
        """尚未建立子題的主題：平鋪該主題的字池（只有 20 字，不假裝能換一組）。"""
        pool = _uniq(theme["pool"])
        n = min(20, len(pool))
        fresh = [c for c in pool if c not in ex]
        stale = [c for c in pool if c in ex]
        rng.shuffle(fresh)
        rng.shuffle(stale)
        chosen = (fresh + stale)[:n]
        rng.shuffle(chosen)
        return {
            "source": "pool", "theme_id": theme["id"], "theme_name": theme["name"],
            "group_id": None, "group_name": theme["short"], "tagline": theme.get("description", ""),
            "can_redraw": len(pool) > n, "stages": [{"name": "", "hint": "", "characters": chosen}],
            "meanings": self._meanings_for(chosen),
        }
