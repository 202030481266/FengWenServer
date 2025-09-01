import logging
import os
import random
import string
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from dotenv import load_dotenv
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.ses.v20201002 import ses_client, models

from src.fengwen2.astrology_views import AstrologyResultsView

# Configure logging
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

    @staticmethod
    def _log_email_action(action: str, email: str, **kwargs):
        """Centralized logging for email actions"""
        extra_info = " ".join(f"{k}: {v}" for k, v in kwargs.items())
        logger.info(f"[EMAIL] {action} for {email}. {extra_info}")

    @staticmethod
    def generate_verification_code(length: int = 6) -> str:
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

            self.client.SendEmail(req)
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

    @staticmethod
    def _convert_full_result_to_html_template_parameters(full_result: Dict[str, Any]) -> Dict[str, Any]:
        """用来将响应的json数据转换为短信模板中的参数"""
        results = AstrologyResultsView.model_validate(full_result)
        bazi_data = results.bazi.data
        liudao_data = results.liudao.data
        zhengyuan_data = results.zhengyuan.data
        template_parameters = {
            # Basic Information
            "name": bazi_data.base_info.name,
            "na_yin": bazi_data.bazi_info.na_yin,
            "gongli": bazi_data.base_info.gongli,
            "nongli": bazi_data.base_info.nongli,
            "sx": bazi_data.sx,
            "xz": bazi_data.xz,
            "bazi": bazi_data.bazi_info.bazi,
            "zhengge": bazi_data.base_info.zhengge or "", # 确保提供一个值

            # Analysis Sections
            "wuxing_desc": bazi_data.wuxing.detail_description,
            "yinyuan_desc": bazi_data.yinyuan.sanshishu_yinyuan,
            "caiyun_desc": bazi_data.caiyun.sanshishu_caiyun.detail_desc,

            # Liudao Sections
            "liudao_now_desc": liudao_data.liudao_info.now_info.liudao_detail_desc,
            "liudao_past_desc": liudao_data.liudao_info.past_info.liudao_detail_desc,
            "liudao_future_desc": liudao_data.liudao_info.future_info.liudao_detail_desc,

            # true love profile
            "face_shape": zhengyuan_data.zhengyuan_info.huaxiang.face_shape,
            "eyebrow_shape": zhengyuan_data.zhengyuan_info.huaxiang.eyebrow_shape,
            "eye_shape": zhengyuan_data.zhengyuan_info.huaxiang.eye_shape,
            "mouth_shape": zhengyuan_data.zhengyuan_info.huaxiang.mouth_shape,
            "nose_shape": zhengyuan_data.zhengyuan_info.huaxiang.nose_shape,
            "body_shape": zhengyuan_data.zhengyuan_info.huaxiang.body_shape,

            # true love traits
            "romantic_personality": zhengyuan_data.zhengyuan_info.tezhi.romantic_personality,
            "family_background": zhengyuan_data.zhengyuan_info.tezhi.family_background,
            "career_wealth": zhengyuan_data.zhengyuan_info.tezhi.career_wealth,
            "marital_happiness": zhengyuan_data.zhengyuan_info.tezhi.marital_happiness,

            # true love guidance
            "love_location": zhengyuan_data.zhengyuan_info.zhiyin.love_location,
            "meeting_method": zhengyuan_data.zhengyuan_info.zhiyin.meeting_method,
            "interaction_model": zhengyuan_data.zhengyuan_info.zhiyin.interaction_model,
            "love_advice": zhengyuan_data.zhengyuan_info.zhiyin.love_advice,

            # true love fortune
            "yunshi_desc": zhengyuan_data.zhengyuan_info.yunshi,

            # Elements Analysis
            "jin_score": int(bazi_data.xiyongshen.jin_score),
            "mu_score": int(bazi_data.xiyongshen.mu_score),
            "shui_score": int(bazi_data.xiyongshen.shui_score),
            "huo_score": int(bazi_data.xiyongshen.huo_score),
            "tu_score": int(bazi_data.xiyongshen.tu_score),
            "tonglei": bazi_data.xiyongshen.tonglei,
            "yilei": bazi_data.xiyongshen.yilei,

            # Ba Zi Summary
            "qiangruo": bazi_data.xiyongshen.qiangruo,
            "xiyongshen_desc": bazi_data.xiyongshen.xiyongshen_desc,
        }
        return {k : str(v) for k, v in template_parameters.items()}

    async def send_astrology_result_email(self, email: str, astrology_result: str) -> bool:
        """Send astrology result to user"""
        try:
            import json

            # Properly escape the JSON for template
            full_result = json.loads(astrology_result)

            req = models.SendEmailRequest()
            req.FromEmailAddress = f"results@{self.domain}"
            req.Destination = [email]
            req.Template = models.Template()
            req.Template.TemplateID = int(self.result_template)
            req.Template.TemplateData = json.dumps(self._convert_full_result_to_html_template_parameters(full_result))
            req.Subject = "Your Astrology Reading Results"

            logger.info(f"[EMAIL] Sending astrology result to {email}")
            self.client.SendEmail(req)
            logger.info(f"[EMAIL] Astrology result email sent successfully to {email}")
            return True

        except TencentCloudSDKException as err:
            logger.error(f"[EMAIL] Send astrology result error for {email}: {err}")
            return False
