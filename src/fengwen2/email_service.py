import json
import logging
import os
import random
import string
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Dict, Any

import redis
from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_credentials.models import Config as CredentialConfig
from alibabacloud_dm20151123 import models as dm_20151123_models
from alibabacloud_dm20151123.client import Client as Dm20151123Client
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models
from dotenv import load_dotenv
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.ses.v20201002 import ses_client, models

from src.fengwen2.astrology_views import AstrologyResultsView

logger = logging.getLogger(__name__)

load_dotenv()


def get_redis_client():
    """Initialize and return Redis client."""
    try:
        REDIS_URL = os.getenv("REDIS_URL")
        if not REDIS_URL:
            raise ValueError("REDIS_URL environment variable not set.")
        client = redis.from_url(REDIS_URL, decode_responses=True)
        client.ping()
        logger.info("Successfully connected to Redis.")
        return client
    except redis.exceptions.ConnectionError as e:
        logger.error(f"Could not connect to Redis: {e}")
        return None
    except ValueError as e:
        logger.error(e)
        return None


redis_client = get_redis_client()


class EmailProvider(Enum):
    """Email service provider types."""
    TENCENT = "tencent"
    ALIBABA = "alibaba"


class BaseEmailProvider(ABC):
    """Abstract base class for email providers."""

    @abstractmethod
    async def send_email(
            self,
            to_email: str,
            subject: str,
            content: str,
            content_type: str = "html",
            from_email: Optional[str] = None,
            **kwargs
    ) -> bool:
        """Send an email through the provider."""
        pass


class TencentEmailProvider(BaseEmailProvider):
    """Tencent Cloud SES email provider."""

    def __init__(self):
        self.secret_id = os.getenv("TENCENTCLOUD_SECRET_ID")
        self.secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY")
        self.domain = os.getenv("EMAIL_DOMAIN", "mail.universalfuture.online")

        if not self.secret_id or not self.secret_key:
            raise ValueError("Missing Tencent Cloud credentials in environment variables")

        self.cred = credential.Credential(self.secret_id, self.secret_key)
        self.client = ses_client.SesClient(self.cred, "ap-hongkong")

    async def send_email(
            self,
            to_email: str,
            subject: str,
            content: str,
            content_type: str = "html",
            from_email: Optional[str] = None,
            template_id: Optional[str] = None,
            template_data: Optional[Dict] = None,
            **kwargs
    ) -> bool:
        """Send email using Tencent Cloud SES."""
        try:
            req = models.SendEmailRequest()
            req.FromEmailAddress = from_email or f"noreply@{self.domain}"
            req.Destination = [to_email]
            req.Subject = subject

            if template_id and template_data:
                # Template-based email
                req.Template = models.Template()
                req.Template.TemplateID = int(template_id)
                req.Template.TemplateData = json.dumps(template_data) if isinstance(template_data,
                                                                                    dict) else template_data
            else:
                # Simple email with content
                if content_type == "html":
                    req.Html = content
                else:
                    req.Text = content

            self.client.SendEmail(req)
            logger.info(f"[TENCENT] Email sent successfully to {to_email}")
            return True

        except TencentCloudSDKException as err:
            logger.error(f"[TENCENT] Error sending email to {to_email}: {err.code} - {err.message}")
            return False
        except Exception as err:
            logger.error(f"[TENCENT] Unexpected error sending email to {to_email}: {err}")
            return False


class AlibabaEmailProvider(BaseEmailProvider):
    """Alibaba Cloud DirectMail email provider."""

    def __init__(self):
        self.account_name = os.getenv("ALIBABA_EMAIL_ACCOUNT")
        self.reply_to_address = os.getenv("ALIBABA_REPLY_TO_ADDRESS", "false").lower() == "true"
        self.endpoint = os.getenv("ALIBABA_EMAIL_ENDPOINT", "dm.aliyuncs.com")  # 华东1 （杭州）
        self.client = self._create_client()

    def _create_client(self) -> Dm20151123Client:
        """Create Alibaba Cloud DirectMail client."""
        config = CredentialConfig(
            type='access_key',
            access_key_id=os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_ID'),
            access_key_secret=os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET'),
        )
        cred = CredentialClient(config)
        config = open_api_models.Config(credential=cred)
        config.endpoint = self.endpoint
        return Dm20151123Client(config)

    async def send_email(
            self,
            to_email: str,
            subject: str,
            content: str,
            content_type: str = "html",
            from_email: Optional[str] = None,
            **kwargs
    ) -> bool:
        """Send email using Alibaba Cloud DirectMail."""
        try:
            request = dm_20151123_models.SingleSendMailRequest(
                account_name=from_email or self.account_name,
                address_type=1,  # 1 for single address
                to_address=to_email,
                subject=subject,
                reply_to_address=self.reply_to_address
            )

            if content_type == "html":
                request.html_body = content
            else:
                request.text_body = content

            runtime = util_models.RuntimeOptions()
            self.client.single_send_mail_with_options(request, runtime)

            logger.info(f"[ALIBABA] Email sent successfully to {to_email}")
            return True

        except Exception as err:
            logger.error(f"[ALIBABA] Error sending email to {to_email}: {err}")
            if hasattr(err, 'data'):
                logger.error(f"[ALIBABA] Error details: {err.data}")
            return False


class EmailService:
    """Unified email service with multiple provider support."""

    _VCODE_PREFIX = "vcode:"
    _VERIFIED_PREFIX = "verified:"

    def __init__(self):
        if not redis_client:
            raise ConnectionError("EmailService cannot operate without a Redis connection.")

        self.redis = redis_client

        # Initialize providers
        self.providers = {}
        self._init_providers()

        # Load configuration
        self.verification_template = os.getenv("EMAIL_TEMPLATE_VERIFICATION", "145744")
        self.result_template = os.getenv("EMAIL_TEMPLATE_ASTROLOGY_RESULT", "145745")
        self.code_expiry_seconds = int(os.getenv("VERIFICATION_CODE_EXPIRY_SECONDS", 300))
        self.verified_status_expiry_seconds = int(os.getenv("VERIFIED_STATUS_EXPIRY_SECONDS", 600))

        # Default providers for different email types
        self.verification_provider = EmailProvider.TENCENT
        self.result_provider = EmailProvider.ALIBABA

    def _init_providers(self):
        """Initialize email providers based on available credentials."""
        # Try to initialize Tencent provider
        try:
            self.providers[EmailProvider.TENCENT] = TencentEmailProvider()
            logger.info("Tencent email provider initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize Tencent provider: {e}")

        # Try to initialize Alibaba provider
        try:
            self.providers[EmailProvider.ALIBABA] = AlibabaEmailProvider()
            logger.info("Alibaba email provider initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize Alibaba provider: {e}")

    def get_provider(self, provider_type: EmailProvider) -> BaseEmailProvider:
        """Get email provider by type."""
        if provider_type not in self.providers:
            raise ValueError(f"Provider {provider_type.value} is not available")
        return self.providers[provider_type]

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
        """Send verification code email using Tencent Cloud (template-based)."""
        try:
            verification_code = self.generate_verification_code()
            redis_key = f"{self._VCODE_PREFIX}{email}"

            provider = self.get_provider(self.verification_provider)

            self._log_email_action(
                "Sending verification code",
                email,
                code="******",
                provider=self.verification_provider.value
            )

            # Use Tencent's template system for verification emails
            success = await provider.send_email(
                to_email=email,
                subject="Email Verification Code",
                content="",  # Not used with template
                template_id=self.verification_template,
                template_data={"code": verification_code}
            )

            if success:
                self.redis.set(redis_key, verification_code, ex=self.code_expiry_seconds)
                self._log_email_action("Verification email sent successfully", email)

            return success

        except Exception as err:
            logger.error(f"[EMAIL] Error sending verification to {email}: {err}")
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
        """Check if email's verified status key exists in Redis."""
        verified_key = f"{self._VERIFIED_PREFIX}{email}"
        is_verified = self.redis.exists(verified_key) > 0

        self._log_email_action("Verification status check", email, is_valid=is_verified)
        return is_verified

    def get_verification_code_for_testing(self, email: str) -> Optional[str]:
        """Get verification code from Redis for testing purposes."""
        return self.redis.get(f"{self._VCODE_PREFIX}{email}")

    @staticmethod
    def _generate_astrology_html_email(template_data: Dict[str, Any]) -> str:
        """Generate HTML email content for astrology results."""
        # This is a simplified version - you should use a proper templating engine
        # or load from an HTML template file
        html_template = """
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>您的星座运势分析结果</title>
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; }
                .content { background: white; padding: 30px; border: 1px solid #e2e8f0; }
                .section { margin-bottom: 25px; }
                .section-title { color: #2d3748; font-size: 18px; font-weight: bold; margin-bottom: 10px; }
                .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 20px; }
                .info-item { padding: 8px; background: #f7fafc; border-radius: 5px; }
                .score { display: inline-block; padding: 3px 8px; background: #edf2f7; border-radius: 3px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>星座运势分析报告</h1>
                    <p>您的个人专属分析已生成</p>
                </div>
                <div class="content">
                    <div class="section">
                        <div class="section-title">基本信息</div>
                        <div class="info-grid">
                            <div class="info-item"><strong>姓名：</strong>{name}</div>
                            <div class="info-item"><strong>生肖：</strong>{sx}</div>
                            <div class="info-item"><strong>星座：</strong>{xz}</div>
                            <div class="info-item"><strong>八字：</strong>{bazi}</div>
                        </div>
                    </div>

                    <div class="section">
                        <div class="section-title">五行分析</div>
                        <p>{wuxing_desc}</p>
                        <div style="margin-top: 10px;">
                            <span class="score">金: {jin_score}</span>
                            <span class="score">木: {mu_score}</span>
                            <span class="score">水: {shui_score}</span>
                            <span class="score">火: {huo_score}</span>
                            <span class="score">土: {tu_score}</span>
                        </div>
                    </div>

                    <div class="section">
                        <div class="section-title">姻缘分析</div>
                        <p>{yinyuan_desc}</p>
                    </div>

                    <div class="section">
                        <div class="section-title">财运分析</div>
                        <p>{caiyun_desc}</p>
                    </div>

                    <div class="section">
                        <div class="section-title">运势指引</div>
                        <p>{yunshi_desc}</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

        # Format the template with data
        return html_template.format(**template_data)

    @staticmethod
    def _convert_full_result_to_template_data(full_result: Dict[str, Any]) -> Dict[str, str]:
        """Convert full result JSON to template data."""
        results = AstrologyResultsView.model_validate(full_result)
        bazi_data = results.bazi.data
        liudao_data = results.liudao.data
        zhengyuan_data = results.zhengyuan.data

        template_data = {
            # Basic Information
            "name": bazi_data.base_info.name,
            "na_yin": bazi_data.bazi_info.na_yin,
            "gongli": bazi_data.base_info.gongli,
            "nongli": bazi_data.base_info.nongli,
            "sx": bazi_data.sx,
            "xz": bazi_data.xz,
            "bazi": bazi_data.bazi_info.bazi,
            "zhengge": bazi_data.base_info.zhengge or "",

            # Analysis Sections
            "wuxing_desc": bazi_data.wuxing.detail_description,
            "yinyuan_desc": bazi_data.yinyuan.sanshishu_yinyuan,
            "caiyun_desc": bazi_data.caiyun.sanshishu_caiyun.detail_desc,

            # Liudao Sections
            "liudao_now_desc": liudao_data.liudao_info.now_info.liudao_detail_desc,
            "liudao_past_desc": liudao_data.liudao_info.past_info.liudao_detail_desc,
            "liudao_future_desc": liudao_data.liudao_info.future_info.liudao_detail_desc,

            # True love profile
            "face_shape": zhengyuan_data.zhengyuan_info.huaxiang.face_shape,
            "eyebrow_shape": zhengyuan_data.zhengyuan_info.huaxiang.eyebrow_shape,
            "eye_shape": zhengyuan_data.zhengyuan_info.huaxiang.eye_shape,
            "mouth_shape": zhengyuan_data.zhengyuan_info.huaxiang.mouth_shape,
            "nose_shape": zhengyuan_data.zhengyuan_info.huaxiang.nose_shape,
            "body_shape": zhengyuan_data.zhengyuan_info.huaxiang.body_shape,

            # True love traits
            "romantic_personality": zhengyuan_data.zhengyuan_info.tezhi.romantic_personality,
            "family_background": zhengyuan_data.zhengyuan_info.tezhi.family_background,
            "career_wealth": zhengyuan_data.zhengyuan_info.tezhi.career_wealth,
            "marital_happiness": zhengyuan_data.zhengyuan_info.tezhi.marital_happiness,

            # True love guidance
            "love_location": zhengyuan_data.zhengyuan_info.zhiyin.love_location,
            "meeting_method": zhengyuan_data.zhengyuan_info.zhiyin.meeting_method,
            "interaction_model": zhengyuan_data.zhengyuan_info.zhiyin.interaction_model,
            "love_advice": zhengyuan_data.zhengyuan_info.zhiyin.love_advice,

            # True love fortune
            "yunshi_desc": zhengyuan_data.zhengyuan_info.yunshi,

            # Elements Analysis
            "jin_score": str(int(bazi_data.xiyongshen.jin_score)),
            "mu_score": str(int(bazi_data.xiyongshen.mu_score)),
            "shui_score": str(int(bazi_data.xiyongshen.shui_score)),
            "huo_score": str(int(bazi_data.xiyongshen.huo_score)),
            "tu_score": str(int(bazi_data.xiyongshen.tu_score)),
            "tonglei": bazi_data.xiyongshen.tonglei,
            "yilei": bazi_data.xiyongshen.yilei,

            # Ba Zi Summary
            "qiangruo": bazi_data.xiyongshen.qiangruo,
            "xiyongshen_desc": bazi_data.xiyongshen.xiyongshen_desc,
        }

        return {k: str(v) for k, v in template_data.items()}

    async def send_astrology_result_email(self, email: str, astrology_result: str) -> bool:
        """Send astrology result email using Alibaba Cloud (HTML-based)."""
        try:
            full_result = json.loads(astrology_result)
            template_data = self._convert_full_result_to_template_data(full_result)

            # Generate HTML content
            html_content = self._generate_astrology_html_email(template_data)

            provider = self.get_provider(self.result_provider)

            self._log_email_action(
                "Sending astrology result",
                email,
                provider=self.result_provider.value
            )

            # Use Alibaba's single send email for results
            success = await provider.send_email(
                to_email=email,
                subject="您的星座运势分析结果",
                content=html_content,
                content_type="html",
                from_email="results@mail.fengculture.com"
            )

            if success:
                self._log_email_action("Astrology result email sent successfully", email)

            return success

        except json.JSONDecodeError as err:
            logger.error(f"[EMAIL] Failed to parse astrology_result JSON: {err}")
            return False
        except Exception as err:
            logger.error(f"[EMAIL] Error sending result to {email}: {err}")
            return False

    async def send_custom_email(
            self,
            to_email: str,
            subject: str,
            content: str,
            content_type: str = "html",
            provider: Optional[EmailProvider] = None,
            **kwargs
    ) -> bool:
        """Send a custom email using specified or default provider."""
        try:
            # Use specified provider or default to Alibaba for general emails
            email_provider = provider or EmailProvider.ALIBABA
            provider_instance = self.get_provider(email_provider)

            self._log_email_action(
                "Sending custom email",
                to_email,
                subject=subject,
                provider=email_provider.value
            )

            success = await provider_instance.send_email(
                to_email=to_email,
                subject=subject,
                content=content,
                content_type=content_type,
                **kwargs
            )

            if success:
                self._log_email_action("Custom email sent successfully", to_email)

            return success

        except Exception as err:
            logger.error(f"[EMAIL] Error sending custom email to {to_email}: {err}")
            return False