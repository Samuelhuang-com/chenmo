"""辰墨軒｜智慧主題選字引擎（v1.1）

設計重點
- 純 Python、無第三方相依，可單獨測試。
- 無狀態：「重抽」靠呼叫端傳入 exclude（上一組字），不在伺服器記憶體保存狀態，
  因此在 Cloud Run 多實例下也能正確運作。
- 每個子題內各階段候選字互不重疊（由驗證保證），所以各階段獨立抽樣即可保證 20 字不重複。
- 子題尚未建立的主題，退回「平鋪字池」模式（該主題的 20 字）；整個字庫讀取失敗時，
  退回舊版 character_pool.txt。
"""
from __future__ import annotations

import json
import random
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# 預言式用語：寓意文字不應出現（規格 §1.2「文化解讀而非預言」）
FORBIDDEN_WORDS = ("必定", "一定會", "註定", "保證", "必然", "命中", "災", "厄", "劫")


class BankError(Exception):
    """字庫設定錯誤。"""


def is_single_han(s: str) -> bool:
    """單一完整漢字（以 Unicode 碼位判斷，不依 UTF-16 單位）。"""
    if len(s) != 1:
        return False
    cp = ord(s)
    return (
        0x4E00 <= cp <= 0x9FFF  # CJK Unified
        or 0x3400 <= cp <= 0x4DBF  # Ext A
        or 0x20000 <= cp <= 0x2A6DF  # Ext B
        or 0xF900 <= cp <= 0xFAFF  # Compatibility
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

    used_chars: set[str] = set()
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
        used_chars.update(pool)
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
        size = g.get("sample_size")
        stages = g.get("stages", [])
        if not isinstance(size, int) or size <= 0:
            errors.append(f"子題 {gid} 的 sample_size 無效")
            continue
        if not stages:
            errors.append(f"子題 {gid} 沒有階段")
            continue
        quota_sum = 0
        seen_in_group: dict[str, str] = {}
        for st in stages:
            sname = st.get("name", "?")
            q = st.get("quota")
            chars = st.get("characters", "")
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
                    errors.append(
                        f"子題 {gid} 的「{ch}」同時出現在「{seen_in_group[ch]}」與「{sname}」（階段候選字不得重疊）"
                    )
                seen_in_group.setdefault(ch, sname)
            used_chars.update(chars)
            if len(set(chars)) < q:
                errors.append(f"子題 {gid}／{sname} 候選字（{len(set(chars))}）少於配額（{q}）")
            elif len(set(chars)) == q:
                warnings.append(f"子題 {gid}／{sname} 候選字剛好等於配額，此階段無法重抽變化")
            elif len(set(chars)) < 2 * q:
                warnings.append(f"子題 {gid}／{sname} 候選字少於配額 2 倍，重抽變化有限")
        if quota_sum != size:
            errors.append(f"子題 {gid} 的配額加總（{quota_sum}）不等於 sample_size（{size}）")

    for ch in sorted(used_chars):
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
        kws = info.get("keywords", [])
        if not kws:
            warnings.append(f"字 {ch} 沒有關鍵詞")
    for ch in mean_map:
        if not is_single_han(ch):
            errors.append(f"字義檔的 key 不是單一漢字：{ch!r}")
        elif ch not in used_chars:
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

    # ----- 載入
    @classmethod
    def load(cls, data_dir: Path | str = DEFAULT_DATA_DIR, *, strict: bool = True) -> "CharacterBank":
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
        return [
            {
                "id": t["id"],
                "name": t["name"],
                "short": t["short"],
                "description": t.get("description", ""),
                "has_groups": bool(t.get("group_ids")),
            }
            for t in self.themes["themes"]
        ]

    def list_groups(self, theme_id: str) -> list[dict]:
        t = self._theme(theme_id)
        return [
            {"id": gid, "name": self.group_by_id[gid]["name"], "tagline": self.group_by_id[gid]["tagline"]}
            for gid in t.get("group_ids", [])
        ]

    def meaning(self, ch: str) -> Optional[dict]:
        info = self.meanings["characters"].get(ch)
        return dict(info) if info else None

    def _theme(self, theme_id: str) -> dict:
        t = self.theme_by_id.get(theme_id)
        if t is None:
            raise KeyError(f"找不到主題：{theme_id}")
        return t

    def _meanings_for(self, chars: Iterable[str]) -> dict:
        m = self.meanings["characters"]
        return {c: m[c] for c in chars if c in m}

    # ----- 抽字
    def pick(
        self,
        theme_id: str,
        group_id: Optional[str] = None,
        exclude: str = "",
        rng: Optional[random.Random] = None,
    ) -> dict:
        """為指定主題產生一組字。

        group_id 省略：主題有子題時隨機挑一個（若有 exclude 且有多個子題，不另外避開，維持簡單）。
        exclude：上一組出現過的字；候選足夠時優先抽沒出現過的字，讓「重抽」確實不同。
        """
        rng = rng or random.Random()
        theme = self._theme(theme_id)
        ex = set(exclude)

        gids = theme.get("group_ids", [])
        if group_id is not None:
            if group_id not in gids:
                raise KeyError(f"主題 {theme_id} 沒有子題 {group_id}")
            gid: Optional[str] = group_id
        else:
            gid = rng.choice(gids) if gids else None

        if gid is None:
            return self._pick_pool(theme, ex, rng)
        return self._pick_group(theme, self.group_by_id[gid], ex, rng)

    def random(self, rng: Optional[random.Random] = None) -> dict:
        rng = rng or random.Random()
        theme = rng.choice(self.themes["themes"])
        return self.pick(theme["id"], rng=rng)

    def _pick_group(self, theme: dict, group: dict, ex: set, rng: random.Random) -> dict:
        stages_out = []
        can_redraw = False
        for st in group["stages"]:
            cands = _uniq(st["characters"])
            q = st["quota"]
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
            "source": "group",
            "theme_id": theme["id"],
            "theme_name": theme["name"],
            "group_id": group["id"],
            "group_name": group["name"],
            "tagline": group["tagline"],
            "summary": group["summary"],
            "prompt": group["prompt"],
            "count": len(all_chars),
            "can_redraw": can_redraw,
            "stages": stages_out,
            "meanings": self._meanings_for(all_chars),
            "bank_version": self.version,
        }

    def _pick_pool(self, theme: dict, ex: set, rng: random.Random) -> dict:
        """尚未建立子題的主題：平鋪該主題的字池（不假裝能重抽）。"""
        pool = _uniq(theme["pool"])
        n = min(20, len(pool))
        fresh = [c for c in pool if c not in ex]
        stale = [c for c in pool if c in ex]
        rng.shuffle(fresh)
        rng.shuffle(stale)
        chosen = (fresh + stale)[:n]
        rng.shuffle(chosen)
        return {
            "source": "pool",
            "theme_id": theme["id"],
            "theme_name": theme["name"],
            "group_id": None,
            "group_name": theme["short"],
            "tagline": theme.get("description", ""),
            "summary": theme.get("description", ""),
            "prompt": theme["prompt"],
            "count": len(chosen),
            "can_redraw": len(pool) > n,
            "stages": [{"name": "", "hint": "", "characters": chosen}],
            "meanings": self._meanings_for(chosen),
            "bank_version": self.version,
        }


# --------------------------------------------------------------------------- 舊字池備援
def load_legacy_pool(path: Path | str) -> list[str]:
    """解析舊版 character_pool.txt：略過空行與 # 註解，去重並只留漢字。"""
    p = Path(path)
    if not p.exists():
        return []
    seen, out = set(), []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for ch in re.sub(r"\s+", "", line):
            if ch not in seen and is_single_han(ch):
                seen.add(ch)
                out.append(ch)
    return out


def pick_legacy(pool: list[str], n: int = 20, rng: Optional[random.Random] = None) -> dict:
    rng = rng or random.Random()
    if len(pool) < n:
        raise BankError(f"舊字池不足 {n} 字（目前 {len(pool)}）")
    chosen = rng.sample(pool, n)
    return {
        "source": "legacy",
        "theme_id": None,
        "theme_name": "",
        "group_id": None,
        "group_name": "隨機靈感",
        "tagline": "",
        "summary": "",
        "prompt": "",
        "count": n,
        "can_redraw": True,
        "stages": [{"name": "", "hint": "", "characters": chosen}],
        "meanings": {},
        "bank_version": "legacy",
    }
