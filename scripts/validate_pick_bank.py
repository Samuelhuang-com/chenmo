#!/usr/bin/env python3
"""驗證自選字主題字庫（app/data/pick/）。有錯誤時退出碼為 1。

用法：python scripts/validate_pick_bank.py [資料夾]
改完 themes.json／groups.json／character_meanings.json 後執行；`pytest -q` 也會自動檢查。
"""
import json
import sys
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.pick_bank import DATA_DIR, validate_data  # noqa: E402


def main() -> int:
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_DIR
    try:
        themes, groups, meanings = (json.loads((d / f).read_text(encoding="utf-8"))
                                    for f in ("themes.json", "groups.json", "character_meanings.json"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"✗ 無法讀取字庫：{e}")
        return 1
    errors, warnings = validate_data(themes, groups, meanings)
    print(f"主題 {len(themes['themes'])} 個；子題 {len(groups['groups'])} 個；字義 {len(meanings['characters'])} 字")
    for g in groups["groups"]:
        n = 1
        for st in g["stages"]:
            n *= comb(len(set(st["characters"])), st["quota"])
        print(f"  · {g['id']}（{g['name']}）約可產生 {n:,} 種不同字組")
    none = [t["short"] for t in themes["themes"] if not t.get("group_ids")]
    if none:
        print(f"  · 尚無子題（以平鋪字池呈現）：{'、'.join(none)}")
    for w in warnings:
        print(f"! 警告：{w}")
    for e in errors:
        print(f"✗ 錯誤：{e}")
    print(f"\n{'驗證失敗' if errors else '✓ 驗證通過'}（{len(errors)} 個錯誤、{len(warnings)} 個警告）")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
