import os
import random
import string
import logging
from typing import Optional
from datetime import datetime, timedelta
from dotenv import load_dotenv
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.ses.v20201002 import ses_client, models

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

class EmailService:
    """Tencent Cloud SES email service"""
    
    def __init__(self):
        self.secret_id = os.getenv("TENCENTCLOUD_SECRET_ID")
        self.secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY")
        self.domain = os.getenv("EMAIL_DOMAIN", "mail.universalfuture.online")
        self.verification_template = os.getenv("EMAIL_TEMPLATE_VERIFICATION", "145744")
        self.result_template = os.getenv("EMAIL_TEMPLATE_ASTROLOGY_RESULT", "145745")
        
        if not self.secret_id or not self.secret_key:
            raise ValueError("Missing Tencent Cloud credentials in environment variables")
        
        self.cred = credential.Credential(self.secret_id, self.secret_key)
        self.client = ses_client.SesClient(self.cred, "ap-hongkong")
        self.verification_codes = {}
        self.verified_emails = {}
    
    def _log_email_action(self, action: str, email: str, **kwargs):
        """Centralized logging for email actions"""
        extra_info = " ".join(f"{k}: {v}" for k, v in kwargs.items())
        logger.info(f"[EMAIL] {action} for {email}. {extra_info}")
    
    def generate_verification_code(self, length: int = 6) -> str:
        """Generate random verification code"""
        return ''.join(random.choices(string.digits, k=length))
    
    async def send_verification_email(self, email: str) -> Optional[str]:
        """Send verification code email"""
        try:
            verification_code = self.generate_verification_code()
            
            req = models.SendEmailRequest()
            req.FromEmailAddress = f"noreply@{self.domain}"
            req.Destination = [email]
            req.Template = models.Template()
            req.Template.TemplateID = int(self.verification_template)
            req.Template.TemplateData = f'{{"code": "{verification_code}"}}'
            req.Subject = "Email Verification Code"
            
            self._log_email_action("Sending verification code", email, 
                                 code=verification_code, template=self.verification_template)
            
            resp = self.client.SendEmail(req)
            self._log_email_action("Email sent successfully", email)
            
            self.verification_codes[email] = verification_code
            return verification_code
            
        except TencentCloudSDKException as err:
            logger.error(f"[EMAIL] TencentCloud error for {email}: {err.code} - {err.message}")
            return None
        except Exception as err:
            logger.error(f"[EMAIL] Unexpected error for {email}: {err}")
            return None
    
    def verify_code(self, email: str, code: str) -> bool:
        """Verify email code"""
        stored_code = self.verification_codes.get(email)
        self._log_email_action("Verifying code", email, provided=code, stored=stored_code)
        
        if stored_code and stored_code == code:
            del self.verification_codes[email]
            self.verified_emails[email] = datetime.now()
            self._log_email_action("Code verification successful", email)
            return True
        
        logger.warning(f"[EMAIL] Code verification failed for {email}")
        return False
    
    def is_email_recently_verified(self, email: str) -> bool:
        """Check if email was verified within last 10 minutes"""
        verification_time = self.verified_emails.get(email)
        if not verification_time:
            self._log_email_action("No verification record", email)
            return False
        
        time_diff = datetime.now() - verification_time
        is_valid = time_diff < timedelta(minutes=10)
        self._log_email_action("Verification status check", email, 
                             valid=is_valid, seconds_ago=int(time_diff.total_seconds()))
        return is_valid
    
    def get_verification_code_for_testing(self, email: str) -> Optional[str]:
        """Get verification code for testing purposes"""
        return self.verification_codes.get(email)
    
    async def send_astrology_result_email(self, email: str, name: str, astrology_result: str) -> bool:
        """Send astrology result to user"""
        try:
            import json
            
            # Properly escape the JSON for template
            escaped_result = astrology_result.replace('"', '\\"').replace('\n', '\\n')
            
            req = models.SendEmailRequest()
            req.FromEmailAddress = f"results@{self.domain}"
            req.Destination = [email]
            req.Template = models.Template()
            req.Template.TemplateID = int(self.result_template)
            req.Template.TemplateData = json.dumps({
                "name": name,
                "result": escaped_result
            })
            req.Subject = "Your Astrology Reading Results"
            
            logger.info(f"[EMAIL] Sending astrology result to {email}")
            resp = self.client.SendEmail(req)
            logger.info(f"[EMAIL] Astrology result email sent successfully to {email}")
            return True
            
        except TencentCloudSDKException as err:
            logger.error(f"[EMAIL] Send astrology result error for {email}: {err}")
            return False