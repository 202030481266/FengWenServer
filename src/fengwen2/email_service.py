import logging
import os
import random
import string
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import redis
from dotenv import load_dotenv
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.ses.v20201002 import ses_client, models

from src.fengwen2.astrology_views import AstrologyResultsView

logger = logging.getLogger(__name__)

load_dotenv()

# --- Redis Client Setup ---
try:
    REDIS_URL = os.getenv("REDIS_URL")
    if not REDIS_URL:
        raise ValueError("REDIS_URL environment variable not set.")
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info("Successfully connected to Redis.")
except redis.exceptions.ConnectionError as e:
    logger.error(f"Could not connect to Redis: {e}")
    redis_client = None
except ValueError as e:
    logger.error(e)
    redis_client = None


class EmailService:
    """Tencent Cloud SES email service with Redis for state management."""

    _VCODE_PREFIX = "vcode:"
    _VERIFIED_PREFIX = "verified:"

    def __init__(self):
        if not redis_client:
            raise ConnectionError("EmailService cannot operate without a Redis connection.")
        self.redis = redis_client

        # tencent config 
        self.secret_id = os.getenv("TENCENTCLOUD_SECRET_ID")
        self.secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY")
        self.domain = os.getenv("EMAIL_DOMAIN", "mail.universalfuture.online")
        self.verification_template = os.getenv("EMAIL_TEMPLATE_VERIFICATION", "145744")
        self.result_template = os.getenv("EMAIL_TEMPLATE_ASTROLOGY_RESULT", "145745")

        # redis config
        self.code_expiry_seconds = int(os.getenv("VERIFICATION_CODE_EXPIRY_SECONDS", 300))  # 5 minutes
        self.verified_status_expiry_seconds = int(os.getenv("VERIFIED_STATUS_EXPIRY_SECONDS", 600))  # 10 minutes

        if not self.secret_id or not self.secret_key:
            raise ValueError("Missing Tencent Cloud credentials in environment variables")

        self.cred = credential.Credential(self.secret_id, self.secret_key)
        self.client = ses_client.SesClient(self.cred, "ap-hongkong")

    @staticmethod
    def _log_email_action(action: str, email: str, **kwargs):
        """Centralized logging for email actions."""
        extra_info = " ".join(f"{k}: {v}" for k, v in kwargs.items())
        logger.info(f"[EMAIL] {action} for {email}. {extra_info}")

    @staticmethod
    def generate_verification_code(length: int = 6) -> str:
        """Generate random verification code."""
        return ''.join(random.choices(string.digits, k=length))

    async def send_verification_email(self, email: str) -> bool:
        """Send verification code email and store it in Redis with an expiry."""
        try:
            verification_code = self.generate_verification_code()
            redis_key = f"{self._VCODE_PREFIX}{email}"

            req = models.SendEmailRequest()
            req.FromEmailAddress = f"noreply@{self.domain}"
            req.Destination = [email]
            req.Template = models.Template()
            req.Template.TemplateID = int(self.verification_template)
            req.Template.TemplateData = f'{{"code": "{verification_code}"}}'
            req.Subject = "Email Verification Code"

            self._log_email_action("Sending verification code", email, code="******", template=self.verification_template)

            self.client.SendEmail(req)
            self._log_email_action("Email sent successfully", email)

            self.redis.set(redis_key, verification_code, ex=self.code_expiry_seconds)
            return True

        except TencentCloudSDKException as err:
            logger.error(f"[EMAIL] TencentCloud error for {email}: {err.code} - {err.message}")
            return False
        except Exception as err:
            logger.error(f"[EMAIL] Unexpected error for {email}: {err}")
            return False

    def verify_code(self, email: str, code: str) -> bool:
        """Verify email code from Redis."""
        redis_key = f"{self._VCODE_PREFIX}{email}"
        stored_code = self.redis.get(redis_key)

        self._log_email_action("Verifying code", email, provided=code, stored=stored_code)

        if stored_code and stored_code == code:
            pipe = self.redis.pipeline()
            pipe.delete(redis_key)
            verified_key = f"{self._VERIFIED_PREFIX}{email}"
            pipe.set(verified_key, "true", ex=self.verified_status_expiry_seconds)
            pipe.execute()
            
            self._log_email_action("Code verification successful", email)
            return True

        logger.warning(f"[EMAIL] Code verification failed for {email}")
        return False

    def is_email_recently_verified(self, email: str) -> bool:
        """Check if email's "verified" status key exists in Redis."""
        verified_key = f"{self._VERIFIED_PREFIX}{email}"
        is_verified = self.redis.exists(verified_key) > 0
        
        self._log_email_action("Verification status check", email, is_valid=is_verified)
        return is_verified

    def get_verification_code_for_testing(self, email: str) -> Optional[str]:
        """Get verification code from Redis for testing purposes."""
        return self.redis.get(f"{self._VCODE_PREFIX}{email}")

    @staticmethod
    def _convert_full_result_to_html_template_parameters(full_result: Dict[str, Any]) -> Dict[str, Any]:
        """Converts the full result JSON to parameters for the email template."""
        # This static method has no state and remains unchanged.
        results = AstrologyResultsView.model_validate(full_result)
        bazi_data = results.bazi.data
        liudao_data = results.liudao.data
        zhengyuan_data = results.zhengyuan.data
        template_parameters = {
             # Basic Information
            "name": bazi_data.base_info.name, "na_yin": bazi_data.bazi_info.na_yin,
            "gongli": bazi_data.base_info.gongli, "nongli": bazi_data.base_info.nongli,
            "sx": bazi_data.sx, "xz": bazi_data.xz, "bazi": bazi_data.bazi_info.bazi,
            "zhengge": bazi_data.base_info.zhengge or "",
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
            "jin_score": int(bazi_data.xiyongshen.jin_score), "mu_score": int(bazi_data.xiyongshen.mu_score),
            "shui_score": int(bazi_data.xiyongshen.shui_score), "huo_score": int(bazi_data.xiyongshen.huo_score),
            "tu_score": int(bazi_data.xiyongshen.tu_score), "tonglei": bazi_data.xiyongshen.tonglei,
            "yilei": bazi_data.xiyongshen.yilei,
            # Ba Zi Summary
            "qiangruo": bazi_data.xiyongshen.qiangruo, "xiyongshen_desc": bazi_data.xiyongshen.xiyongshen_desc,
        }
        return {k: str(v) for k, v in template_parameters.items()}

    async def send_astrology_result_email(self, email: str, astrology_result: str) -> bool:
        """Send astrology result to user."""
        # This method is stateless and remains unchanged.
        try:
            full_result = json.loads(astrology_result)
            template_data = self._convert_full_result_to_html_template_parameters(full_result)

            req = models.SendEmailRequest()
            req.FromEmailAddress = f"results@{self.domain}"
            req.Destination = [email]
            req.Template = models.Template()
            req.Template.TemplateID = int(self.result_template)
            req.Template.TemplateData = json.dumps(template_data)
            req.Subject = "Your Astrology Reading Results"

            logger.info(f"[EMAIL] Sending astrology result to {email}")
            self.client.SendEmail(req)
            logger.info(f"[EMAIL] Astrology result email sent successfully to {email}")
            return True

        except TencentCloudSDKException as err:
            logger.error(f"[EMAIL] Send astrology result error for {email}: {err}")
            return False
        except json.JSONDecodeError as err:
            logger.error(f"[EMAIL] Failed to parse astrology_result JSON: {err}")
            return False
        except Exception as err:
            logger.error(f"[EMAIL] Unexpected error sending result to {email}: {err}")
            return False