# 辰墨軒｜線上測字（第一階段）

問事者用手機寫下問題與一個字，解題老師在電腦上**即時看到每一筆的書寫順序**，可重播、逐筆檢視，再回覆解字。

技術：Python 3.12 · FastAPI · Jinja2 · WebSocket · Firestore · Cloud Run

## 本機執行（Windows / VSCode）

```powershell
cd chenmo
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env        # 預設：SQLite 存檔 + 老師密碼 dev123
uvicorn app.main:app --reload --port 8000
```

| 網址 | 用途 |
|---|---|
| http://localhost:8000/ | 首頁 |
| http://localhost:8000/ask | 問字（用手機測試請見下方） |
| http://localhost:8000/master | 老師端（密碼 dev123） |
| http://localhost:8000/master/history | 已解紀錄（可搜尋字或問題） |

本機資料存在 `C:\Users\<你的帳號>\.chenmo\chenmo.db`（SQLite），重啟伺服器不會消失。刻意放在 OneDrive 之外，避免同步時鎖住檔案。

**用手機實測手寫**：電腦與手機在同一個 Wi-Fi 下，改用 `uvicorn app.main:app --host 0.0.0.0 --port 8000`，手機開 `http://<電腦的區網IP>:8000/ask`。若 Windows 防火牆跳出詢問，請允許。

執行測試：`pytest -q`

## 自選字：依方向挑字（選填）

學生按「自選字」後，**預設仍是立刻出 20 個隨機字（`app/data/pick_pool.txt`），做法與以前完全相同**。面板上多一排選填的「方向」按鈕（人生方向、情感人際、心境修養…）：選了方向，就改出 20 個彼此有關聯的字，並在字格上方顯示這組字的主題短句與思考路徑。

- 目前「人生方向」「情感人際」「心境修養」各有 1 個完整子題（突破困境、珍惜關係、找回平靜；每階段 8 選 4）；其餘 9 個方向先平鋪該方向的 20 字，沒有「換一組」。
- 字義**不會**顯示給問事者（避免搶在老師的解讀之前）；老師端的自選字資訊與解字稿的【此字】會註明「方向」。字義檔 `character_meanings.json` 目前只供編輯參考與驗證。
- 資料在 `app/data/pick/`（`themes.json` 方向、`groups.json` 子題與階段、`character_meanings.json` 字義），老師可直接編輯。
- 改完執行 `python scripts/validate_pick_bank.py`；`pytest -q` 也會自動檢查（缺字義、階段候選字重疊、配額不符等都會擋下）。
- 主題字庫載入失敗時，自選字自動退回隨機字池，不影響問字。
- API：`GET /api/pick`（不帶參數＝隨機）、`GET /api/pick?theme=life[&group=..&exclude=..]`、`GET /api/pick/themes`。換一組由前端傳 `exclude`（上一組的字），伺服器不記憶狀態。

## 解字資料自動帶出

老師打開案件時，若問事者有填「寫的是哪個字」，系統會自動在解字欄帶出五段內容；也可以在「此字」欄改字後按「帶出字資料」。

| 段落 | 來源 |
|---|---|
| 【此字】 | 注音（教育部辭典）、部首、總筆畫、康熙筆畫（Unihan，部首以本字計）、筆跡觀察（筆數比對、停頓、擦除、位置大小） |
| 【五行】 | 依康熙筆畫尾數、依部首；規則在 `app/data/wuxing_rules.json`，老師可自行修改 |
| 【古字說法】 | 《說文解字》說解、反切、重文（古文、籀文）、段玉裁注節錄 |
| 【字義】 | 教育部《重編國語辭典修訂本》釋義與常用詞 |
| 【解讀】 | AI 草稿（需設定 `ANTHROPIC_API_KEY`），結合問題、拆字與筆跡 |

標示「AI 草稿」的段落請老師審閱修改後再送出。

**送給問事者的只有【解讀】**；【此字】【五行】【古字說法】【字義】是老師的解字稿，會自動暫存，問事者看不到。解字欄下方會即時預覽問事者將看到的內容。

**收回與重送**：已送出的字可按「收回」，問事者頁面會回到「等待老師解讀」；修改後按「重送解讀」即可。已解紀錄會顯示送出次數。

## 封測功能（功能開關）

新功能上線前，可以只開放給指定 Email。目前有開關的功能：`yao`（六龍問爻）。

| 誰看得到 | 條件 |
|---|---|
| 老師 | 一律看得到 |
| 封測名單 | 用 Google 登入，且 Email 在名單內 |
| 其他人 | 看不到入口；直接打網址也是 404 |

- 名單管理：老師端「封測名單」`/master/flags`，可新增／移除 Email、一鍵正式開放，60 秒內生效，不必重新部署
- 也可以用環境變數預先放名單：`FEATURE_YAO_EMAILS=a@gmail.com,b@gmail.com`；`FEATURE_YAO_ALL=true` 則直接全開
- 資料存在 `feature_flags/yao`（Firestore）或 SQLite 的 `feature_flags` 表
- 新增問爻路由時一律掛 `Depends(require_feature("yao"))`；模板用 `'yao' in request.state.features` 判斷是否顯示入口

## 六龍問爻：排盤引擎

`app/services/liuyao/` 是純規則的六爻排盤，不連網、不依賴外部套件：64 卦、京房八宮世應、納甲、六親、六神、伏神、卦身、互錯綜，以及干支曆（立春換年、節氣換月、子初換日可切換、旬空）。節氣用天文公式計算，誤差約 15 分鐘；起卦時間落在交節前後 1 小時內會提醒核對。

- 老師排盤工具：`/master/yao/paipan`，選六爻與時間即可排盤，用來和自己慣用的排法對照
- 標準答案：`tests/liuyao/golden_cases.json`，發現排法不同時，把那組卦照格式加進去，`pytest -q` 就會檢查

## 部署到 Google Cloud

見 [docs/GCP部署指南.md](docs/GCP部署指南.md)。簡要流程（在 Cloud Shell）：
```bash
nano deploy/config.sh          # 填專案 ID、老師信箱
bash deploy/gcp_setup.sh       # 一次性：API、Firestore、服務帳號、金鑰
bash deploy/deploy.sh          # 部署
bash deploy/set_oauth.sh       # 設定 Google 登入後再部署一次
```

## 專案結構

```
app/
  main.py                 進入點、Session、錯誤頁
  config.py               環境變數設定
  models.py               案件模型、100 字驗證（以 Unicode 字元計）
  auth.py                 老師登入（Google OAuth / 開發密碼）
  repositories/           memory（本機）與 firestore（雲端），介面相同
  services/realtime.py    WebSocket 連線中樞（之後可換 Redis）
  services/strokes.py     筆畫清理、復原/清除重建
  routers/                pages / api / master / ws
  templates/              Jinja2 頁面
  static/js/
    brush-pad.js          手寫板（座標、時間、壓力）
    ink.js                依筆速變化粗細的墨跡繪製
    replay.js             依真實時間重播、逐筆檢視
    ws-client.js          自動重連、斷線排隊、sync 確認
    ask.js / master-*.js  各頁面邏輯
deploy/                   gcloud 腳本
deploy/github-actions-deploy.yml  GitHub Actions 設定（請移到 .github/workflows/deploy.yml）
```

## 筆畫資料格式

每一筆存成一個事件（Firestore：`cases/{id}/events/{n}`）：
```json
{"type": "stroke", "seq": 3, "t0": 1728350001000,
 "points": [[0.21, 0.30, 0, 0.5], [0.25, 0.31, 16, 0.5]]}
```
- `points`：`[x, y, 距本筆開始毫秒, 壓力]`，x/y 正規化為 0–1
- `undo` / `clear` 也存成事件；老師端可勾選「含擦除過程」看到被擦掉的筆

## 下一階段（第二階段）
- 手寫辨識候選字（HanziLookupJS）
- 常用字字庫匯入：部首、筆畫、說文解字、字義
- 五行規則引擎與老師自訂對照表，自動帶入解字面板
