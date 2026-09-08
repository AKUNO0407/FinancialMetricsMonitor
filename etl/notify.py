# etl/notify.py

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv

load_dotenv()


SMTP_HOST = os.getenv(
    "SMTP_HOST",
    "smtp.gmail.com",
)

SMTP_PORT = int(
    os.getenv(
        "SMTP_PORT",
        "465",
    )
)

SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO")


def send_failure_email(
    subject: str,
    body: str,
):
    if not SMTP_USER:
        raise RuntimeError(
            "SMTP_USER is not configured."
        )

    if not SMTP_PASSWORD:
        raise RuntimeError(
            "SMTP_PASSWORD is not configured."
        )

    if not ALERT_EMAIL_TO:
        raise RuntimeError(
            "ALERT_EMAIL_TO is not configured."
        )

    message = EmailMessage()

    message["Subject"] = subject
    message["From"] = SMTP_USER
    message["To"] = ALERT_EMAIL_TO

    message.set_content(body)

    with smtplib.SMTP_SSL(
        SMTP_HOST,
        SMTP_PORT,
        timeout=30,
    ) as smtp:

        smtp.login(
            SMTP_USER,
            SMTP_PASSWORD,
        )

        smtp.send_message(message)


if __name__ == "__main__":

    send_failure_email(
        subject="[TEST] FinancialMetricsMonitor Alert",
        body=(
            "This is a test alert from "
            "FinancialMetricsMonitor."
        ),
    )

    print("Test alert email sent.")