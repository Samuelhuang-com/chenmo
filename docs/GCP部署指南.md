# 辰墨軒｜Google Cloud 部署指南

> 這份指南從 Google Cloud Console 開始，一步步把網站部署到 Cloud Run。
> 指令都在 **Cloud Shell**（Console 右上角的 `>_` 圖示）執行，不需要在 Windows 安裝 gcloud。

---

## 0. 會用到的 Google Cloud 服務

| 服務 | 用途 | 第一階段費用估計 |
|---|---|---|
| **Cloud Run** | 執行 FastAPI 網站與 WebSocket | 有免費額度，小流量通常每月 0 至數十元台幣 |
| **Firestore**（原生模式） | 存案件與筆跡 | 免費額度：每日 5 萬次讀取、2 萬次寫入 |
| **Secret Manager** | 存 session 金鑰、Google 登入用戶端密鑰 | 每個密鑰每月約 0.06 美元 |
| **Cloud Build / Artifact Registry** | 從原始碼建置容器映像 | 有每月免費建置額度，偶爾部署幾乎不花錢 |
| **OAuth 用戶端**（API 和服務） | 老師用 Google 帳號登入 | 免費 |

區域一律使用 **asia-east1（台灣彰化）**，延遲最低。

> 以上費用是依目前公開價格估算，實際以 Google Cloud 計價頁為準。第 7 節會教你設定預算警示。

---

## 1. 建立或選擇專案（Console）

1. 前往 <https://console.cloud.google.com>
2. 上方專案選單 →「新增專案」，名稱填 `chenmo`。系統會產生專案 ID，例如 `chenmo-438712`，請記下來
3. 確認專案已連結帳單帳戶（左側選單「帳單」）

> 若想沿用你先前架設的專案也可以，只要把專案 ID 填進 `deploy/config.sh`。不同服務各自獨立，不會互相影響。

## 2. 上傳程式碼到 Cloud Shell

兩種方式，二選一：

**A. 從 GitHub（推薦）**：先把 `chenmo` 資料夾推到你的 GitHub repo，再在 Cloud Shell 執行：
```bash
git clone https://github.com/<你的帳號>/chenmo.git
cd chenmo
```

**B. 直接上傳**：把 `chenmo` 資料夾壓成 zip，在 Cloud Shell 右上角「⋮ → 上傳」，然後：
```bash
unzip chenmo.zip && cd chenmo
```

## 3. 一次性初始化

編輯 `deploy/config.sh`，填入專案 ID 與老師的 Google 信箱：
```bash
nano deploy/config.sh
```
```bash
PROJECT_ID="chenmo-438712"
MASTER_EMAILS="你的信箱@gmail.com"
```
執行初始化（啟用 API、建立 Firestore、服務帳號、session 金鑰）：
```bash
bash deploy/gcp_setup.sh
```
第一次部署（取得網址）：
```bash
bash deploy/deploy.sh
```
完成後會顯示網址，例如 `https://chenmo-xxxxx-de.a.run.app`。這時已可打開問字頁，但老師端還不能登入，請接著做第 4 節。

## 4. 設定老師用 Google 帳號登入（Console）

### 4.1 OAuth 同意畫面
1. Console 左側選單 →「API 和服務」→「OAuth 同意畫面」（新版介面稱為 **Google Auth Platform**）
2. 應用程式名稱：`辰墨軒`；使用者支援電子郵件：你的信箱
3. 目標對象：選 **外部**
4. 發布狀態維持「測試中」，並在「測試使用者」加入所有老師的 Gmail
   - 只要求 `openid`、`email`、`profile` 這三個基本權限，不需要送 Google 審查
   - 測試模式最多 100 位測試使用者，對老師端綽綽有餘

### 4.2 建立 OAuth 用戶端
1. 「API 和服務」→「憑證」→「建立憑證」→「OAuth 用戶端 ID」
2. 應用程式類型：**網頁應用程式**
3. 名稱：`chenmo-web`
4. **已授權的重新導向 URI** 加入兩筆：
   - `https://<你的 Cloud Run 網址>/master/auth/callback`
   - `http://localhost:8000/master/auth/callback`（本機開發用）
5. 建立後會顯示「用戶端 ID」與「用戶端密鑰」

### 4.3 存入 Secret Manager 並重新部署
```bash
bash deploy/set_oauth.sh     # 貼上用戶端 ID 與密鑰
bash deploy/deploy.sh
```
打開 `https://<網址>/master`，用 Google 登入。只有列在 `MASTER_EMAILS` 的帳號能進入老師端，其他帳號會看到「此帳號沒有老師權限」。

## 4.4 啟用 AI 解字草稿（選用）

不設定也能帶出部首、筆畫、五行、《說文解字》與教育部辭典字義。設定後，「古字說法」「字義」「五行」會多一段 AI 補充，「解讀」會有一份草稿。

1. 到 <https://console.anthropic.com> 建立 API Key（這是 Anthropic 的主控台，不是 Google Cloud）
2. 在 Cloud Shell：
```bash
bash deploy/set_ai_key.sh
bash deploy/deploy.sh
```
每次「帶出字資料」會呼叫一次 Claude API，結果會快取在案件上，重開頁面不會重複計費。

## 5. 綁定自己的網域（選用）

**方式 A：Cloud Run 網域對應**（最簡單，asia-east1 支援）
1. Console →「Cloud Run」→「管理自訂網域」→「新增對應」
2. 選服務 `chenmo`，輸入網域，例如 `chenmo.tw`
3. 依畫面指示到網域商（如 Gandi、PChome 買網域）新增 DNS 紀錄
4. 憑證會自動簽發，約 15 分鐘到數小時
5. **記得回到 4.2 把新網域的 callback 網址也加進去**

> 這個功能目前仍標示為預覽版。若日後需要正式版 SLA，可改用 **方式 B：外部應用程式負載平衡器 + 無伺服器網路端點群組**。這個方式每月有固定費用，流量大了再考慮。

## 6. GitHub Actions 自動部署（選用，建議）

先把 `deploy/github-actions-deploy.yml` 移到 `.github/workflows/deploy.yml`。之後推上 `main` 分支就自動測試並部署，使用 **Workload Identity Federation**，不需要下載任何金鑰檔。在 Cloud Shell 執行（把變數改成你的）：

```bash
source deploy/config.sh
GITHUB_REPO="<你的帳號>/chenmo"
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')

# 部署用服務帳號
gcloud iam service-accounts create chenmo-deployer --display-name="GitHub 部署"
DEPLOYER="chenmo-deployer@$PROJECT_ID.iam.gserviceaccount.com"
for role in roles/run.admin roles/cloudbuild.builds.editor roles/artifactregistry.admin \
            roles/storage.admin roles/serviceusage.serviceUsageConsumer roles/secretmanager.viewer; do
  gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$DEPLOYER" --role=$role --condition=None
done
# 允許它以 Cloud Run 執行身分部署
gcloud iam service-accounts add-iam-policy-binding \
  "$RUN_SA@$PROJECT_ID.iam.gserviceaccount.com" \
  --member="serviceAccount:$DEPLOYER" --role=roles/iam.serviceAccountUser

# Workload Identity Pool（只信任你這個 repo）
gcloud iam workload-identity-pools create github --location=global --display-name="GitHub"
gcloud iam workload-identity-pools providers create-oidc github-oidc \
  --location=global --workload-identity-pool=github \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='$GITHUB_REPO'"
gcloud iam service-accounts add-iam-policy-binding $DEPLOYER \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$GITHUB_REPO"

echo "GCP_WIF_PROVIDER = projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github-oidc"
echo "GCP_DEPLOY_SA    = $DEPLOYER"
```

到 GitHub repo →「Settings → Secrets and variables → Actions」新增四個 secret：
`GCP_PROJECT_ID`、`GCP_WIF_PROVIDER`、`GCP_DEPLOY_SA`、`MASTER_EMAILS`

## 7. 營運設定

- **預算警示**：Console →「帳單」→「預算與快訊」→ 建立預算，例如每月 NT$500，在 50%、90%、100% 時寄信通知
- **查看紀錄**：Console →「Cloud Run」→ `chenmo` →「記錄」
- **查看資料**：Console →「Firestore」→ `cases` 集合
- **Firestore 備份**（上線後建議）：Console →「Firestore」→「災難復原」→ 開啟每日備份
- **資料保存期限**：日後可加 TTL 政策，例如 180 天後自動刪除案件，以符合隱私承諾

## 8. 第一階段的架構限制與擴充路線

| 現況 | 原因 | 何時要改 | 怎麼改 |
|---|---|---|---|
| `max-instances=1` | 即時連線中樞在記憶體內 | 同時線上超過約 200 人 | 加 Memorystore（Redis）Pub/Sub，替換 `app/services/realtime.py` 的 Hub |
| `min-instances=0` | 省錢，沒人用時不計費 | 第一位使用者覺得開頁太慢（冷啟動約 2–4 秒） | 改 `--min-instances 1`（會有固定月費） |
| IP 限流在記憶體 | 單一實例夠用 | 多實例時 | 改用 Redis 或 Cloud Armor |
