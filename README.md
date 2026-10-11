# B＋85 退休年度規劃工具（瀏覽器版）

這是 **免費 GitHub Pages 網站的公開程式原始碼**，適合一般使用者在瀏覽器進行年初預算、年末結算與年度紀錄備份。它不會連接銀行或券商，不會下單或提領，且尚非正式 ACTIVE 的真實提款系統。

## 開啟網站

啟用 GitHub Pages 後，網站網址為：

**https://rucifa.github.io/retirement-b85-web/**

程式首次需要連線下載固定版本的 Pyodide / NumPy；**使用者無需安裝 Python**。後續每次年初輸入資產、已知 CPI 與日期，查看 B＋85 建議；年末輸入實際支出及資產餘額，按確認結算。

## 資料與隱私

- 財務紀錄保存在使用者自己的瀏覽器 IndexedDB，**不自動上傳 GitHub、Google 或本站伺服器**。
- 需要跨裝置、重新安裝瀏覽器或清除瀏覽器資料時，請先匯出 JSON，再於新瀏覽器匯入。此 JSON 可能包含敏感的財務資料，請妥善保管。
- 本公開儲存庫只有靜態 UI 和通用退休政策演算法，**不包含個人持倉、年度紀錄、GitHub 密碼或私人研究備份**。
- USD/TWD 假設固定 30；CPI 需使用當時已公布的可信資料並自行核對；畫面上的 2036、27,000,000 及 CPI 數字純屬示範，並非個人事實。

## GitHub Pages 一次性設定

在 [Settings → Pages](https://github.com/rucifa/retirement-b85-web/settings/pages) 選擇 **Deploy from a branch**，Branch 選 **main**，Folder 選 **/(root)**，按 Save。Pages 顯示已發布後，開啟上面網址。

## 版本與驗證

- B＋85 v3.4.0 政策來源鎖定 SHA256：`54dd2718a098c7f8182fcc44db980c523c2859fdaa276c50e81e8f8ea8712f10`。
- 原私人研究儲存庫的瀏覽器原型曾通過 Chromium 真實 Pyodide／NumPy 年初→年末→JSON 匯出匯入端對端測試。
- 本公共儲存庫保留最少量的公開測試碼；正式 ACTIVE 實際提款與真人可用性仍需進一步驗收。

本工具僅用於研究、演練與帳務核對；結果不代表已驗證的實際提款指令。
