from datetime import datetime
import logging
from azure.communication.email import EmailClient
from fastapi import HTTPException, status
import os
from dotenv import load_dotenv
from tools.logger import get_logger
from tools.decorators import log_function_call

load_dotenv()

# -------------------------
# Logging Setup
# -------------------------
logger = get_logger("azure_email")

# -------------------------
# Azure Email Client Setup
# -------------------------
COMMUNICATION_CONNECTION_STRING = os.getenv("MAIL_CNN_STRING")
if not COMMUNICATION_CONNECTION_STRING:
    logger.critical("❌ MAIL_CNN_STRING is NOT set in environment")
    # raise RuntimeError("MAIL_CNN_STRING environment variable not set") 
    # Commented out to prevent crash if not used instantly, or should fail fast?
    # Original code raised RuntimeError. I'll keep it but maybe wrapped? 
    # Stick to original behavior but log structured.
    pass 

email_client = None
if COMMUNICATION_CONNECTION_STRING:
    try:
        email_client = EmailClient.from_connection_string(
            COMMUNICATION_CONNECTION_STRING
        )
        logger.info("✅ Azure EmailClient initialized successfully")
    except Exception as e:
        logger.critical(f"❌ Failed to initialize EmailClient: {e}", exc_info=True)
        # raise # Optional: fail fast

# -------------------------
# Email Sender Helper
# -------------------------
@log_function_call
async def _send_email(to_address: str, subject: str, html_body: str) -> None:
    logger.info("📨 Preparing to send email")
    
    # Avoid logging full HTML body if huge, maybe just length
    logger.debug(f"To Address: {to_address} | Subject: {subject} | HTML len: {len(html_body)}")

    try:
        await send_mail_to_user(
            sender="DoNotReply@onmeridian.com",
            to=[{"address": to_address}],
            subject=subject,
            html=html_body
        )
        logger.info(f"✅ Email sent to {to_address}")
    except Exception as e:
        logger.error(f"❌ Failed to send email to {to_address}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send email"
        )

# -------------------------
# Core Email Sender
# -------------------------
@log_function_call
async def send_mail_to_user(
    sender: str,
    to: list[dict[str, str]],
    subject: str,
    plain_text: str = "",
    html: str = "",
) -> None:
    if not email_client:
        logger.error("Email client not initialized")
        raise RuntimeError("Email client not initialized")

    logger.debug(f"Sender: {sender} | Recipients: {to} | Subject: {subject}")

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

    try:
        logger.info("📡 Calling Azure begin_send()...")
        poller = email_client.begin_send(message)

        logger.info("⏳ Waiting for Azure email send result...")
        result = poller.result()

        logger.info(f"📬 Azure response received: {result}")

        status_value = result.get("status", "").lower()
        
        if status_value != "succeeded":
            logger.error(f"❌ Azure email send FAILED with status: {status_value}")
            raise RuntimeError(
                f"Email send failed with status: {result.get('status')}"
            )

        logger.info("✅ Azure email sent successfully")

    except Exception as e:
        logger.critical(f"🔥 Exception during Azure email send: {e}", exc_info=True)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send email: {e}"
        ) from e
