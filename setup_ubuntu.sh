#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo " 阿Vi每日趨勢報 — Ubuntu / Linux 安裝腳本"
echo "============================================================"
echo

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 1. System packages ────────────────────────────────────────
echo "[安裝] 更新系統套件..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv curl ca-certificates

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[OK] Python $PY_VER"

# ── 2. Install uv ────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    echo "[安裝] 安裝 uv 套件管理器..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
fi
echo "[OK] uv $(uv --version)"

# ── 3. Install Python dependencies ───────────────────────────
echo
echo "[安裝] 安裝 Python 依賴套件..."
uv pip install -r requirements.txt --system 2>/dev/null || \
    python3 -m pip install -r requirements.txt

# ── 4. Install Playwright + system dependencies ───────────────
echo
echo "[安裝] 安裝 Playwright Chromium 及系統依賴..."
python3 -m playwright install-deps chromium
python3 -m playwright install chromium
echo "[OK] Playwright Chromium 安裝完成"

# ── 5. Reminder ──────────────────────────────────────────────
echo
echo "[確認] 請確認 MailSetting.txt 已填入："
echo "  AIProvider    = gemini 或 anthropic"
echo "  GeminiAPIKey  = 你的 Gemini API Key"
echo "  Sender        = 你的 Gmail 地址"
echo "  Receiver      = 收件人（多人用分號隔開）"
echo "  AppPassword   = Gmail 應用程式密碼（16碼）"
echo

# ── 6. Optional test email ────────────────────────────────────
read -rp "是否要寄送測試信？(y/n): " answer
if [[ "$answer" =~ ^[Yy]$ ]]; then
    echo
    echo "[測試] 寄送測試信..."
    python3 main.py --test
fi

# ── 7. Offer to set up cron job ───────────────────────────────
echo
read -rp "是否要設定每天早上 8:00 自動執行排程？(y/n): " setup_cron
if [[ "$setup_cron" =~ ^[Yy]$ ]]; then
    CRON_LINE="0 8 * * * cd $SCRIPT_DIR && python3 main.py >> $SCRIPT_DIR/trend_cron.log 2>&1"
    # Check if already exists
    if crontab -l 2>/dev/null | grep -qF "trend_reporter"; then
        echo "[跳過] cron 排程已存在"
    else
        (crontab -l 2>/dev/null; echo "# trend_reporter"; echo "$CRON_LINE") | crontab -
        echo "[OK] cron 排程已設定：每天 08:00 執行"
    fi
fi

echo
echo "============================================================"
echo " 安裝完成！執行方式："
echo "   python3 main.py             完整執行"
echo "   python3 main.py --debug     顯示瀏覽器視窗"
echo "   python3 main.py --test      寄送測試信"
echo
echo " 手動設定 cron 排程："
echo "   crontab -e"
echo "   加入: 0 8 * * * cd $SCRIPT_DIR && python3 main.py >> trend_cron.log 2>&1"
echo "============================================================"
