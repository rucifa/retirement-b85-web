# B＋85 退休年度工具｜GitHub Pages 瀏覽器版（2026-10-11）

**狀態：GitHub Pages 靜態站原始碼已建立；網頁必須在 GitHub Settings > Pages 啟用後，才有可驗證的正式網址。** 研究演練／影子測試，不是券商授權提款，不接銀行，不自動交易。

## 一般使用者

1. 網頁載入時從固定版本 Pyodide 0.29.5 CDN 下載瀏覽器版 Python/NumPy（第一次需要網路）。
2. 在「年初核准」輸入退休資產、現金、股債比例、**當時已知** CPI 和公布日期；顯示 B＋85 建議生活費、PoS 與現金橋接資訊。
3. 年底在「年末結算」輸入實際支出和年底投資資產、安全現金；檢查資產結轉，隔年自動帶入狀態。
4. 「歷年紀錄」可下載 **JSON 備份**，或將備份重新匯入。資料保存在*同一個瀏覽器與同一個網站來源（IndexedDB）*，不會上傳到 GitHub；**不同裝置、瀏覽器、無痕模式不會自動同步**。務必定期自行匯出備份。

首次展示畫面的數字（2036、27,000,000、2,400,000、CPI 110/125）全部是**假設演練，不是實際個人資產或正式 CPI**。

## 為什麼沒有後端 Python？

網站僅包含 HTML/CSS/JavaScript、Web Worker，以及 v3.4.0 的完整 Python 政策原始碼；Web Worker 用 Pyodide 在使用者自己的瀏覽器執行 `workflow.py` 和**相同 SHA256** 的 `retirement_model_v340.py`，而非另寫 JS 政策公式。政策原始檔的 SHA256 為：

`54dd2718a098c7f8182fcc44db980c523c2859fdaa276c50e81e8f8ea8712f10`

USD/TWD 固定 30；不啟用 FX 排程，亦不新增 CPI 排程。CPI 值目前仍由使用者輸入，**不聲稱自動驗證公告版本**。B＋85 PoS 使用研究用途的 4,096 次內層取樣，並非正式決策精度的外部校準。

## 發布

本專案 GitHub repository 是 **private**。GitHub Free 不支援私有 repo 的 GitHub Pages；需 GitHub Pro/Team/Enterprise 等符合的方案，或另建*獨立公開的純網站 repo*（切勿將包含私人研究資料的原 repo 改成 public）。私人 repo 的 Pages 網站除企業特殊權限外通常**公開可瀏覽**，所以此 `gh-pages` 分支專門只包含可公開網站原始碼，沒有持倉或使用者年度紀錄。

1. GitHub：`rucifa/retirement-model-research` → Settings → Pages。
2. **Build and deployment** → Source → **Deploy from a branch**；選擇 `gh-pages`、`/(root)`、Save。
3. 等 GitHub 在 Pages Settings 顯示發布完成，再點 **Visit site**；專案頁面的預期位置為 `https://rucifa.github.io/retirement-model-research/`（**未啟用及未驗收前不可宣稱網址可用**）。
4. 若 Settings 無法啟用私人 repo Pages，需使用者自行處理 GitHub 方案或另外授權建立*只含網站靜態檔*的 public repo。

## 安全與驗收

- 不收集券商、銀行帳密；不傳送資產/支出至 GitHub/Google/第三方 API。只有首次取回必要的 Pyodide runtime/npm 及本站程式。
- 研究區隔：不變更 frozen v3.3.9、不啟用 `DOCUMENTED` ACTIVE、不直接寫入正式研究 CPI 或任何交易紀錄。
- 保留年度順序、日期先後、預算與已付款分開、不可重複結算；一次性 Emergency、不明入金、超預算，轉人工核查而非自動認列。
- JSON 備份 SHA256 為**意外損壞檢查**，並非防惡意改寫的數位簽章；不要在共用電腦使用。
- 實際下載的 Pyodide/NumPy 版本是否在真實瀏覽器順利執行，必須經真正網路端到端測試；單元測試或靜態 JS 驗證不能取代。

## 專案檔案

- `index.html`、`static/*`：繁體中文年初／年末／歷史紀錄操作 UI。
- `pyodide-worker.js`：隔離背景 Python runtime，避免阻塞畫面。
- `bridge.py`：只提供有白名單的年初、年末、資料儲存／備份命令，不允許任意程式碼。
- `workflow.py`、`policy/*.py`：沿用先前驗證的 B＋85 年度帳務與政策原始碼。
- `tests/test_pages_bridge.py`：由 Python 原引擎檢查重新載入、匯入驗證、年初到隔年、異常拒絕。
