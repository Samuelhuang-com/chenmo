# 辰墨軒｜智慧主題選字 v1.1 交付包

目錄結構與規格 §6.2 相同，可直接複製進網站專案的 `app/`。

## 快速開始
```bash
python scripts/validate_character_bank.py   # 驗證字庫（有錯誤時退出碼為 1）
pytest -q tests                             # 20 項測試
python scripts/build_demo.py                # 產生 ui/character_picker_demo.html（單檔原型）
```
直接用瀏覽器打開 `ui/character_picker_demo.html` 即可操作。

## 接進網站（FastAPI）
```python
from api.characters import router as characters_router
app.include_router(characters_router)
```
前端把 `character_picker.template.html` 裡的 `API_BASE` 改為 `"/api/characters"` 即走後端。
舊字池請放在 `data/character_pool.txt`（執行期備援用）。

## 擴充字庫
1. 在 `groups.json` 新增子題，並把 id 加進對應主題的 `group_ids`。
2. 在 `character_meanings.json` 補上新字的寓意。
3. 執行驗證腳本；零錯誤才提交。
