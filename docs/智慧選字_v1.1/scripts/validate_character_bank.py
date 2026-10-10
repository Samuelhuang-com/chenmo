#!/usr/bin/env python3
"""驗證字庫（可放進 GitHub Actions；有 error 時以退出碼 1 結束，讓部署中止）。

用法：
    python scripts/validate_character_bank.py            # 驗證預設 data/ 目錄
    python scripts/validate_character_bank.py path/to/data
"""
import json
import sys
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.character_picker import validate_data  # noqa: E402


def main() -> int:
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data"
    try:
        themes = json.loads((data_dir / "themes.json").read_text(encoding="utf-8"))
        groups = json.loads((data_dir / "groups.json").read_text(encoding="utf-8"))
        meanings = json.loads((data_dir / "character_meanings.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"✗ 無法讀取字庫：{e}")
        return 1

    errors, warnings = validate_data(themes, groups, meanings)

    print(f"主題 {len(themes['themes'])} 個；子題 {len(groups['groups'])} 個；字義 {len(meanings['characters'])} 字")
    for g in groups["groups"]:
        combos = 1
        for st in g["stages"]:
            combos *= comb(len(set(st["characters"])), st["quota"])
        print(f"  · {g['id']}（{g['name']}）可產生約 {combos:,} 種不同字組")
    no_group = [t["short"] for t in themes["themes"] if not t.get("group_ids")]
    if no_group:
        print(f"  · 尚無子題（目前以平鋪字池呈現）：{'、'.join(no_group)}")

    for w in warnings:
        print(f"! 警告：{w}")
    for e in errors:
        print(f"✗ 錯誤：{e}")
    if errors:
        print(f"\n驗證失敗：{len(errors)} 個錯誤、{len(warnings)} 個警告")
        return 1
    print(f"\n✓ 驗證通過（{len(warnings)} 個警告）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
