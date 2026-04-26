#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo " 阿Vi每日趨勢報 — Ubuntu / Linux 安裝腳本"
echo "============================================================"
echo

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON="$VENV_DIR/bin/python"

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
    # Persist to .bashrc only if not already there
    grep -qxF 'export PATH="$HOME/.local/bin:$PATH"' ~/.bashrc \
        || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
fi
export PATH="$HOME/.local/bin:$PATH"
echo "[OK] uv $(uv --version)"

# ── 3. Create virtual environment ────────────────────────────
echo
echo "[安裝] 建立虛擬環境 $VENV_DIR ..."
# uv venv is faster; fall back to python3 -m venv
if command -v uv &>/dev/null; then
    uv venv "$VENV_DIR" --python python3
else
    python3 -m venv "$VENV_DIR"
fi
echo "[OK] 虛擬環境建立完成"

# ── 4. Install Python dependencies into venv ─────────────────
echo
echo "[安裝] 安裝 Python 依賴套件到虛擬環境..."
if command -v uv &>/dev/null; then
    uv pip install -r requirements.txt --python "$PYTHON"
else
    "$PYTHON" -m pip install -r requirements.txt
fi
echo "[OK] 依賴套件安裝完成"

# ── 5. Install Playwright + system dependencies ───────────────
echo
echo "[安裝] 安裝 Playwright Chromium 及系統依賴..."
"$PYTHON" -m playwright install-deps chromium
"$PYTHON" -m playwright install chromium
echo "[OK] Playwright Chromium 安裝完成"

# ── 6. Create run wrapper script ─────────────────────────────
cat > "$SCRIPT_DIR/run.sh" <<EOF
#!/usr/bin/env bash
# 使用虛擬環境執行 TrendReporter
cd "$SCRIPT_DIR"
exec "$PYTHON" main.py "\$@"
EOF
chmod +x "$SCRIPT_DIR/run.sh"
echo "[OK] 建立執行腳本: run.sh"

# ── 7. Reminder ──────────────────────────────────────────────
echo
echo "[確認] 請確認 MailSetting.txt 已填入："
echo "  AIProvider    = gemini 或 anthropic"
echo "  GeminiAPIKey  = 你的 Gemini API Key"
echo "  Sender        = 你的 Gmail 地址"
echo "  Receiver      = 收件人（多人用分號隔開）"
echo "  AppPassword   = Gmail 應用程式密碼（16碼）"
echo

if [ ! -f "$SCRIPT_DIR/MailSetting.txt" ]; then
    cp "$SCRIPT_DIR/MailSetting.example.txt" "$SCRIPT_DIR/MailSetting.txt"
    echo "[建立] MailSetting.txt 已從範本建立，請編輯填入設定"
    echo "  nano $SCRIPT_DIR/MailSetting.txt"
    echo
fi

# ── 8. Optional test email ────────────────────────────────────
read -rp "是否要寄送測試信？(y/n): " answer
if [[ "$answer" =~ ^[Yy]$ ]]; then
    echo
    echo "[測試] 寄送測試信..."
    "$PYTHON" main.py --test
fi

# ── 9. Offer to set up cron job ───────────────────────────────
echo
read -rp "是否要設定每天早上 8:00 自動執行排程？(y/n): " setup_cron
if [[ "$setup_cron" =~ ^[Yy]$ ]]; then
    CRON_LINE="0 8 * * * $SCRIPT_DIR/run.sh >> $SCRIPT_DIR/trend_cron.log 2>&1"
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
echo "   ./run.sh                    完整執行（四國擷取+翻譯+寄信）"
echo "   ./run.sh --debug            顯示瀏覽器視窗（除錯用）"
echo "   ./run.sh --test             寄送測試信"
echo "   ./run.sh --country JP       只處理日本"
echo
echo " 或直接用虛擬環境 Python："
echo "   $PYTHON main.py"
echo
echo " 手動設定 cron 排程："
echo "   crontab -e"
echo "   加入: 0 8 * * * $SCRIPT_DIR/run.sh >> $SCRIPT_DIR/trend_cron.log 2>&1"
echo "============================================================"
