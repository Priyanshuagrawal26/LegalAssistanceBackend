from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional
import os
from dotenv import load_dotenv

load_dotenv()
 
def verify_otp_template(name: str, otp: str) -> str:
    year = datetime.now().year
    return f"""
          <div style="background-color: #e7f0f8; font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 0; border: 2px solid #f0f0f0; border-radius: 30px; box-shadow: 0 10px 15px -5px rgba(0, 0, 0, 0.1); overflow: hidden;">
          <!-- Header -->
          <div style="background-color: #2E5BFF; border-bottom: 4px solid white; box-shadow: 0 5px 10px -5px rgba(0, 0, 0, 0.1); height: 80px; width: 100%; display: flex; justify-content: center; align-items: center;">
              <h2 style="color: white; margin: auto; font-size: 20px; font-weight: bold; text-align: center;">Password Reset Request</h2>
          </div>
 
          <!-- Content -->
          <div style="padding: 20px; background-color: #ffffff;">
              <div style="text-align: center; margin-bottom: 20px;">
                  <span style="font-size: 32px; font-weight: bold; color: #2E5BFF; text-decoration: none; display: inline-block;">Leagal_Assistance</span>
              </div>
 
              <p style="font-size: 14px; color: #333; margin: 0; margin-top: 10px;">
                  Hello <strong>{name}</strong>,
              </p>
 
              <p style="font-size: 14px; color: #333; margin: 10px 0;">
                  We received a request to reset your password. Use the One-Time Password (OTP) below to reset your password:
              </p>
 
              <div style="text-align: center; margin: 20px 0;">
                  <h2 style="border: 2px dashed #2E5BFF; padding: 10px 20px; color: #2E5BFF; background-color: #f9f9f9; display: inline-block; border-radius: 5px; font-family: monospace;">{otp}</h2>
              </div>
 
              <p style="font-size: 14px; color: #333; margin: 10px 0;">
                  This OTP is valid for the next <strong>10 minutes</strong>. If you did not request a password reset, you can safely ignore this email. Your account is secure.
              </p>
 
              <p style="font-size: 14px; color: #333; margin: 10px 0;">
                  For your security, do not share this OTP with anyone. If you face any issues, feel free to reach out to us.
              </p>
          </div>
 
          <!-- Footer -->
          <div style="background-color: #f9f9f9; padding: 15px; text-align: center; border-top: 1px solid #ddd; border-radius: 0 0 30px 30px;">
              <p style="font-size: 12px; color: #777; margin: 0;">
                  Please do not reply to this email. If you need further support, visit our
                  <a href="{
                    os.getenv("SUPPORT_URL")
                  }" target="_blank" style="color: #2E5BFF; text-decoration: none;">Support Page</a>.
              </p>
              <p style="font-size: 12px; color: #777; margin: 10px 0;">&copy; {datetime.now().year} Legal Assistance. All rights reserved.</p>
          </div>
        </div>"""
 