import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Telegram ──────────────────────────────────────────────────────────────
    BOT_TOKEN        = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS        = list(map(int, os.getenv("ADMIN_IDS", "123456789").split(",")))
    SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "support")
    WEBAPP_URL       = os.getenv("WEBAPP_URL", "https://your-domain.com")

    # ── СБП реквизиты (куда платят клиенты) ──────────────────────────────────
    SBP_PHONE     = os.getenv("SBP_PHONE", "+79001234567")
    SBP_BANK      = os.getenv("SBP_BANK", "Тинькофф")
    SBP_RECIPIENT = os.getenv("SBP_RECIPIENT", "Иван И.")
