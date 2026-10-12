# B＋85 95/99 Inverse Solver：2026-10-12 本地整合檢查報告

來源：使用者上傳 retirement-b85-web-main.zip（全部原始檔案；28/28 SOURCE_SHA256 驗證通過）。
套用：B85_Inverse_95_99_CPI_Research_Patch_2026-10-12.zip，先 dry-run，再 --apply；凍結核心原 SHA 不變。

本地已驗證：
- 4 項 inverse capacity regression PASS。
- 10 項 pages bridge regression PASS。
- 13 項 calendar first year regression PASS。
- 7 項 personalized spending regression PASS。
- 15 項 official CPI regression PASS。
- 總計 49/49 Python PASS；Node static/app.js、static/cpi-official.js、pyodide-worker.js、static/dashboard.js syntax PASS。
- 更新後 SOURCE_SHA256.json 28/28 PASS；凍結政策 core hash 完全不變。
- 合成資料情境下成功以既有 Python 年度核准紀錄反算 95%／99% 的初始內層 PoS 生活費容量；只讀、不修改既有帳本。

仍未驗收／限制：
- 真正 Chromium／Pyodide E2E 目前無法在本環境執行：本機 http://127.0.0.1 被瀏覽器管理策略阻擋，外部 Pyodide CDN 也無法進行 DNS 連線。此項不可宣稱 PASS。
- GitHub Actions、Pages、公開網站部署尚未進行。本包僅本地候選源碼，不是正式網頁。
- 95/99 只有必要資產初始內層 PoS 逆向容量候選；完整動態終生 Floor／市場／模型精度及外部驗證尚未認證，不能宣稱「最高安全提款額」。
- 資料含 2026 官方 CPI 公開快照，不是未來實際 CPI。

建議：上傳本包至新 GitHub 研究分支，讓 Actions 跑真正 Python + Pyodide/Chromium，解決所有失敗後再考慮合併 main；不要直接覆蓋 main。
