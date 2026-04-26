"""HTML email builder and SMTP sender for TrendReporter.

Reuses and refactors the logic from TrendReporter_Chrome/send_email.py.
"""

import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import Settings


COUNTRY_NAMES = {
    "TW": "台灣",
    "HK": "香港",
    "JP": "日本",
    "KR": "韓國",
}


def build_html(country_code: str, items: list[dict]) -> str:
    country_name = COUNTRY_NAMES.get(country_code, country_code)
    today = datetime.now().strftime("%Y/%m/%d")

    rows = ""
    for item in items:
        keyword = item.get("keyword", "")
        keyword_zh = item.get("keyword_zh", keyword)
        kw_cell = f"{keyword}({keyword_zh})" if keyword_zh and keyword_zh != keyword else keyword

        news_lines = []
        for news in item.get("news", [])[:3]:
            title = news.get("title", "")
            title_zh = news.get("title_zh", title)
            url = news.get("url", "#")
            link = f'<a href="{url}" style="color:#1a73e8;text-decoration:none">{title}</a>'
            if title_zh and title_zh != title:
                news_lines.append(f"{link}({title_zh})")
            else:
                news_lines.append(link)

        news_cell = "<br>".join(news_lines) if news_lines else "（無新聞資料）"

        rows += f"""
        <tr>
          <td style="padding:10px 14px;border:1px solid #e0e0e0;vertical-align:top;
                     min-width:130px;font-weight:600;background:#fafafa">{kw_cell}</td>
          <td style="padding:10px 14px;border:1px solid #e0e0e0;vertical-align:top;
                     line-height:1.8">{news_cell}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head><meta charset="UTF-8"></head>
<body style="font-family:'Noto Sans TC',Arial,sans-serif;margin:0;padding:20px;background:#f5f5f5">
  <div style="max-width:820px;margin:0 auto;background:#fff;border-radius:8px;
              box-shadow:0 2px 8px rgba(0,0,0,.1);overflow:hidden">
    <div style="background:#1a73e8;padding:20px 28px">
      <h1 style="margin:0;color:#fff;font-size:1.4em">阿Vi的每日趨勢報 — {country_name}</h1>
      <p style="margin:6px 0 0;color:#cce0ff;font-size:0.9em">{today} ・ Google Trends 熱門關鍵字</p>
    </div>
    <div style="padding:20px 28px">
      <table style="width:100%;border-collapse:collapse;font-size:0.95em">
        <thead>
          <tr>
            <th style="padding:10px 14px;border:1px solid #e0e0e0;background:#e8f0fe;
                       text-align:left;width:22%">關鍵字</th>
            <th style="padding:10px 14px;border:1px solid #e0e0e0;background:#e8f0fe;
                       text-align:left">新聞</th>
          </tr>
        </thead>
        <tbody>{rows}
        </tbody>
      </table>
    </div>
    <div style="padding:14px 28px;background:#f8f9fa;border-top:1px solid #e0e0e0;
                font-size:0.8em;color:#888">
      此郵件由 阿Vi每日趨勢報 自動發送 ・ 資料來源：Google Trends
    </div>
  </div>
</body>
</html>"""


def send_notification(settings: Settings, country_code: str, error_msg: str) -> None:
    country_name = COUNTRY_NAMES.get(country_code, country_code)
    subject = f"[Notification] 翻譯API失敗-{country_name}"
    today = datetime.now().strftime("%Y/%m/%d %H:%M")
    html_body = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head><meta charset="UTF-8"></head>
<body style="font-family:'Noto Sans TC',Arial,sans-serif;margin:0;padding:20px;background:#f5f5f5">
  <div style="max-width:640px;margin:0 auto;background:#fff;border-radius:8px;
              box-shadow:0 2px 8px rgba(0,0,0,.1);overflow:hidden">
    <div style="background:#d93025;padding:20px 28px">
      <h1 style="margin:0;color:#fff;font-size:1.2em">⚠ 翻譯 API 失敗通知</h1>
      <p style="margin:6px 0 0;color:#fdd;font-size:0.9em">{today} ・ {country_name}</p>
    </div>
    <div style="padding:20px 28px">
      <p>國家 <strong>{country_name}</strong> 的翻譯 API 呼叫失敗，郵件已使用原文寄出。</p>
      <p style="font-weight:600">錯誤訊息：</p>
      <pre style="background:#f8f8f8;border:1px solid #e0e0e0;border-radius:4px;
                  padding:12px;font-size:0.9em;overflow-x:auto;white-space:pre-wrap">{error_msg}</pre>
    </div>
    <div style="padding:14px 28px;background:#f8f9fa;border-top:1px solid #e0e0e0;
                font-size:0.8em;color:#888">
      此通知由 阿Vi每日趨勢報 自動發送
    </div>
  </div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.sender
    msg["To"] = settings.sender
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    print(f"  → 寄送翻譯失敗通知至 {settings.sender} ...", end=" ", flush=True)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(settings.sender, settings.app_password)
        server.sendmail(settings.sender, [settings.sender], msg.as_bytes())
    print("✓ 完成")


def send_email(settings: Settings, country_code: str, items: list[dict]) -> None:
    country_name = COUNTRY_NAMES.get(country_code, country_code)
    subject = f"阿Vi的每日趨勢報-{country_name}"
    html_body = build_html(country_code, items)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.sender
    msg["To"] = "; ".join(settings.receiver)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    print(f"  → 寄送 [{country_name}] 至 {settings.receiver} ...", end=" ", flush=True)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(settings.sender, settings.app_password)
        server.sendmail(settings.sender, settings.receiver, msg.as_bytes())
    print("✓ 完成")
