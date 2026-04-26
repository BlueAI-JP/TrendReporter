@echo off
chcp 65001 >nul
echo ============================================================
echo  阿Vi每日趨勢報 — Windows 安裝腳本
echo ============================================================
echo.

:: ── 1. Check Python ──────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 未找到 Python，請先安裝 Python 3.10+ 後再執行此腳本
    echo 下載：https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python 已安裝
python --version

:: ── 2. Install/check uv ──────────────────────────────────────
uv --version >nul 2>&1
if errorlevel 1 (
    echo [安裝] 安裝 uv 套件管理器...
    pip install uv
    if errorlevel 1 (
        echo [警告] uv 安裝失敗，改用 pip
        goto :use_pip
    )
)
echo [OK] uv 已安裝
uv --version

:: ── 3. Install Python dependencies via uv ────────────────────
echo.
echo [安裝] 安裝 Python 依賴套件...
uv pip install -r requirements.txt
if errorlevel 1 (
    echo [警告] uv pip 失敗，改用 pip
    goto :use_pip
)
goto :install_playwright

:use_pip
echo [安裝] 使用 pip 安裝依賴套件...
pip install -r requirements.txt
if errorlevel 1 (
    echo [錯誤] 套件安裝失敗，請檢查網路連線
    pause
    exit /b 1
)

:install_playwright
:: ── 4. Install Playwright browser ────────────────────────────
echo.
echo [安裝] 安裝 Playwright Chromium 瀏覽器（約 150MB）...
python -m playwright install chromium
if errorlevel 1 (
    echo [錯誤] Playwright 瀏覽器安裝失敗
    pause
    exit /b 1
)
echo [OK] Playwright Chromium 安裝完成

:: ── 5. Verify config ─────────────────────────────────────────
echo.
echo [確認] 請確認 MailSetting.txt 已填入以下資訊：
echo   AIProvider    = gemini 或 anthropic
echo   GeminiAPIKey  = 你的 Gemini API Key
echo   Sender        = 你的 Gmail 地址
echo   Receiver      = 收件人（多人用分號隔開）
echo   AppPassword   = Gmail 應用程式密碼（16碼）
echo.

:: ── 6. Test email ─────────────────────────────────────────────
set /p test_mail="是否要寄送測試信？(y/n): "
if /i "%test_mail%"=="y" (
    echo.
    echo [測試] 寄送測試信...
    python main.py --test
)

echo.
echo ============================================================
echo  安裝完成！執行方式：
echo    python main.py             完整執行（擷取+翻譯+寄信）
echo    python main.py --debug    顯示瀏覽器視窗（除錯用）
echo    python main.py --test     寄送測試信
echo.
echo  Windows Task Scheduler 排程設定：
echo    程式：python
echo    引數：main.py
echo    目錄：%~dp0
echo ============================================================
pause
