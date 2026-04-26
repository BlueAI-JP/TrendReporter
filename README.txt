========================================
 阿Vi的每日趨勢報 v2 — 獨立版使用說明
========================================

【版本說明】
  本版本為獨立執行版，使用 Playwright 瀏覽器自動化擷取 Google Trends
  資料，透過 AI API (Gemini 或 Anthropic) 批次翻譯，最後以 SMTP 寄信。
  可排程於 Windows Task Scheduler 或 Ubuntu/Mac cron job。

【檔案清單】
  main.py          主程式（入口點）
  scraper.py       Playwright 瀏覽器擷取模組
  translator.py    AI 批次翻譯模組（Gemini / Anthropic）
  mailer.py        HTML 郵件組合 + SMTP 寄信模組
  config.py        設定檔載入模組
  MailSetting.txt  使用者設定檔（必須填寫）
  requirements.txt Python 套件清單
  setup_windows.bat  Windows 一鍵安裝
  setup_mac.sh       macOS 一鍵安裝
  setup_ubuntu.sh    Ubuntu 一鍵安裝

【首次安裝】

  Windows：
    雙擊 setup_windows.bat 執行

  macOS：
    chmod +x setup_mac.sh && ./setup_mac.sh

  Ubuntu：
    chmod +x setup_ubuntu.sh && ./setup_ubuntu.sh

【設定 MailSetting.txt】

  必填項目：
    AIProvider   = gemini 或 anthropic
    GeminiAPIKey = 你的 Gemini API Key
                   （至 https://aistudio.google.com/app/apikey 取得）
    Sender       = 你的 Gmail 地址
    AppPassword  = Gmail 應用程式密碼（16碼，不是登入密碼）
                   （Google 帳號 > 安全性 > 兩步驟驗證 > 應用程式密碼）
    Receiver     = 收件人，多人用分號(;)隔開

  選填項目：
    AnthropicAPIKey = Anthropic API Key（AIProvider=anthropic 時填）
    AIModel         = 自訂模型名稱（空白則用預設）
    BrowserMode     = headless（背景）或 headed（顯示視窗）

【執行方式】

  完整執行（四國擷取 + 翻譯 + 寄信）：
    python main.py

  只處理特定國家：
    python main.py --country JP

  只擷取+翻譯，不寄信（方便測試）：
    python main.py --no-email

  從已存在的 trend_data.json 直接翻譯並寄信：
    python main.py --from-json

  寄送測試信（確認 SMTP 設定是否正確）：
    python main.py --test

  開啟瀏覽器視窗除錯模式（並儲存截圖）：
    python main.py --debug

【Windows Task Scheduler 排程設定】

  1. 開啟「工作排程器」
  2. 建立基本工作
  3. 設定觸發程序：每天早上 8:00
  4. 設定動作：
       程式：python
       引數：main.py
       起始位置：D:\MyClaudeAI\TrendReporterCode\TrendReporter

【Ubuntu cron 排程設定】

  執行 crontab -e，加入：
    0 8 * * * cd /path/to/TrendReporter && python3 main.py >> trend_cron.log 2>&1

【除錯提示】

  問題：找不到關鍵字
    → 執行 python main.py --debug，查看 debug_XX_list.png 截圖
    → 確認 Google Trends 頁面是否正常載入
    → 可改為 BrowserMode=headed 觀察瀏覽器行為

  問題：翻譯 API 失敗
    → 確認 GeminiAPIKey 或 AnthropicAPIKey 已正確填寫
    → Gemini API Key 格式：AIzaSy...（39碼）
    → Anthropic API Key 格式：sk-ant-...

  問題：郵件寄送失敗
    → 確認 AppPassword 為應用程式密碼（非登入密碼）
    → 確認 Gmail 已開啟兩步驟驗證
    → 確認 Gmail 帳號已啟用 SMTP 存取

========================================
