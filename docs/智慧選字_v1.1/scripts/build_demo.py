#!/usr/bin/env python3
"""把 data/ 的字庫內嵌進 UI 範本，產生可直接開啟的單檔原型 ui/character_picker_demo.html。

用法：python scripts/build_demo.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    d = ROOT / "data"
    themes = json.loads((d / "themes.json").read_text(encoding="utf-8"))["themes"]
    groups = json.loads((d / "groups.json").read_text(encoding="utf-8"))["groups"]
    meanings = json.loads((d / "character_meanings.json").read_text(encoding="utf-8"))["characters"]
    data = json.dumps({"themes": themes, "groups": groups, "meanings": meanings}, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")  # 避免 </script> 提前結束
    tpl = (ROOT / "ui" / "character_picker.template.html").read_text(encoding="utf-8")
    assert "/*__DATA__*/null" in tpl
    out = ROOT / "ui" / "character_picker_demo.html"
    out.write_text(tpl.replace("/*__DATA__*/null", data), encoding="utf-8")
    print(f"✓ 已產生 {out.relative_to(ROOT)}（{out.stat().st_size/1024:.0f} KB）")


if __name__ == "__main__":
    main()
