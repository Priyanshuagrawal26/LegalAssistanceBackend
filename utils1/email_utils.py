from datetime import datetime
import logging
from azure.communication.email import EmailClient
from fastapi import HTTPException, status
import os
from dotenv import load_dotenv

load_dotenv()

# -------------------------
# Logging Setup
# -------------------------
logger = logging.getLogger("azure_email")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# -------------------------
# Azure Email Client Setup
# -------------------------
COMMUNICATION_CONNECTION_STRING = os.getenv("MAIL_CNN_STRING")

logger.debug("🔍 Loading Azure Email configuration...")
logger.debug(f"MAIL_CNN_STRING exists: {bool(COMMUNICATION_CONNECTION_STRING)}")

if not COMMUNICATION_CONNECTION_STRING:
    logger.critical("❌ MAIL_CNN_STRING is NOT set in environment")
    raise RuntimeError("MAIL_CNN_STRING environment variable not set")

try:
    email_client = EmailClient.from_connection_string(
        COMMUNICATION_CONNECTION_STRING
    )
    logger.info("✅ Azure EmailClient initialized successfully")
except Exception as e:
    logger.critical(f"❌ Failed to initialize EmailClient: {e}")
    raise

# -------------------------
# Email Sender Helper
# -------------------------
async def _send_email(to_address: str, subject: str, html_body: str) -> None:
    logger.info("📨 Preparing to send email")
    logger.debug(f"To Address: {to_address}")
    logger.debug(f"Subject: {subject}")
    logger.debug(f"HTML length: {len(html_body)}")

    try:
        await send_mail_to_user(
            sender="DoNotReply@onmeridian.com",
            to=[{"address": to_address}],
            subject=subject,
            html=html_body
        )
        logger.info(f"✅ Email sent to {to_address}")
    except Exception as e:
        logger.error(f"❌ Failed to send email to {to_address}")
        logger.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send email"
        )

# -------------------------
# Core Email Sender
# -------------------------
async def send_mail_to_user(
    sender: str,
    to: list[dict[str, str]],
    subject: str,
    plain_text: str = "",
    html: str = "",
) -> None:

    logger.info("🚀 send_mail_to_user() called")
    logger.debug(f"Sender: {sender}")
    logger.debug(f"Recipients: {to}")
    logger.debug(f"Subject: {subject}")
    logger.debug(f"Plain text length: {len(plain_text)}")
    logger.debug(f"HTML length: {len(html)}")

    message = {
        "senderAddress": sender,
        "content": {
            "subject": subject,
            "plainText": plain_text,
            "html": html,
        },
        "recipients": {
            "to": to
        },
    }

    logger.debug("📦 Email payload constructed")
    logger.debug(message)

    try:
        logger.info("📡 Calling Azure begin_send()...")
        poller = email_client.begin_send(message)

        logger.info("⏳ Waiting for Azure email send result...")
        result = poller.result()

        logger.info("📬 Azure response received")
        logger.debug(f"Azure response: {result}")

        status_value = result.get("status", "").lower()
        logger.info(f"📊 Email status: {status_value}")

        if status_value != "succeeded":
            logger.error("❌ Azure email send FAILED")
            logger.error(result)
            raise RuntimeError(
                f"Email send failed with status: {result.get('status')}"
            )

        logger.info("✅ Azure email sent successfully")

    except Exception as e:
        logger.critical("🔥 Exception during Azure email send")
        logger.exception(e)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send email: {e}"
        ) from e
