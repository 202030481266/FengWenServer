import json
import logging
import os
import random
import string
import warnings
from abc import ABC, abstractmethod
from enum import Enum
from functools import wraps
from typing import Optional, Dict, Any, Tuple

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


class EmailError(Exception):
    """Base exception for email service errors"""
    pass


class EmailValidationError(EmailError):
    """Email validation errors"""
    pass


class EmailProviderError(EmailError):
    """Email provider related errors"""
    pass


class EmailDeliveryError(EmailError):
    """Email delivery errors"""
    pass


class EmailFormatError(EmailValidationError):
    """Invalid email format"""
    pass


class EmailNotExistError(EmailValidationError):
    """Email address does not exist or is unreachable"""
    pass


class EmailBlacklistedError(EmailDeliveryError):
    """Email address is blacklisted"""
    pass


class EmailRateLimitError(EmailDeliveryError):
    """Rate limit exceeded"""
    pass


class EmailTemplateError(EmailProviderError):
    """Email template error"""
    pass


class EmailSendFailedError(EmailDeliveryError):
    """General email sending failure"""
    pass


class VerificationCodeExpiredError(EmailError):
    """Verification code has expired"""
    pass


class VerificationCodeInvalidError(EmailError):
    """Verification code is invalid"""
    pass


class VerificationFailedError(EmailError):
    """General verification failure"""
    pass


def deprecated(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        warnings.warn(f"{func.__name__} is deprecated",
                      DeprecationWarning, stacklevel=2)
        return func(*args, **kwargs)

    return wrapper


def validate_email_format(email: str) -> bool:
    """Basic email format validation"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def get_redis_client():
    """Initialize and return Redis client."""
    try:
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            raise ValueError("REDIS_URL environment variable not set.")
        client = redis.from_url(redis_url, decode_responses=True)
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


class EmailSendResult:
    """Result object for email sending operations"""
    def __init__(self, success: bool, message: str = "", error_code: str = None):
        self.success = success
        self.message = message
        self.error_code = error_code


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
    ) -> EmailSendResult:
        """Send an email through the provider."""
        pass


class TencentEmailProvider(BaseEmailProvider):
    """Tencent Cloud SES email provider."""

    # Common Tencent error codes and their user-friendly messages
    ERROR_MESSAGES = {
        "InvalidParameterValue.InvalidEmailAddress": "Invalid email address format",
        "InvalidParameterValue.EmailAddressNotExist": "Email address does not exist",
        "InvalidParameterValue.EmailContentIsTooLarge": "Email content is too large",
        "RequestLimitExceeded.SendEmailRequestLimit": "Too many requests, please try again later",
        "ResourceNotFound.TemplateNotExist": "Email template not found",
        "FailedOperation.EmailAddressInBlacklist": "Email address is blacklisted",
        "FailedOperation.FrequencyLimit": "Sending too frequently, please wait a moment",
        "FailedOperation.ExceedSendLimit": "Daily sending limit exceeded",
        "InvalidParameterValue.RepeatedEmailAddress": "Duplicate email address",
    }

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
    ) -> EmailSendResult:
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
            return EmailSendResult(True, "Email sent successfully")

        except TencentCloudSDKException as err:
            logger.error(f"[TENCENT] Error sending email to {to_email}: {err.code} - {err.message}")
            
            # Map Tencent error codes to specific exceptions
            if err.code == "InvalidParameterValue.InvalidEmailAddress":
                raise EmailFormatError("Invalid email address format")
            elif err.code == "InvalidParameterValue.EmailAddressNotExist":
                raise EmailNotExistError("Email address does not exist")
            elif err.code == "FailedOperation.EmailAddressInBlacklist":
                raise EmailBlacklistedError("Email address is blacklisted")
            elif err.code in ["RequestLimitExceeded.SendEmailRequestLimit", "FailedOperation.FrequencyLimit", "FailedOperation.ExceedSendLimit"]:
                raise EmailRateLimitError("Rate limit exceeded, please try again later")
            elif err.code == "ResourceNotFound.TemplateNotExist":
                raise EmailTemplateError("Email template not found")
            elif err.code == 'FailedOperation.UnsupportMailType':
                raise EmailProviderError('Unsupported Email provider! Please Use a Valid Email!')
            else:
                error_msg = self.ERROR_MESSAGES.get(err.code, f"Failed to send email: {err.message}")
                raise EmailSendFailedError(error_msg)
                
        except Exception as err:
            logger.error(f"[TENCENT] Unexpected error sending email to {to_email}: {err}")
            raise EmailSendFailedError("An unexpected error occurred while sending email")


class AlibabaEmailProvider(BaseEmailProvider):
    """Alibaba Cloud DirectMail email provider."""

    # Common Alibaba error codes and their user-friendly messages
    ERROR_MESSAGES = {
        "InvalidEmail.Malformed": "Invalid email address format",
        "InvalidEmail.NotExist": "Email address does not exist or is unreachable",
        "InvalidDomain": "Invalid email domain",
        "InvalidSendMail": "Failed to send email, please check the recipient address",
        "InvalidTemplate": "Email template error",
        "ReceiverBlacklist": "Recipient email is blacklisted",
        "SpamTooMuch": "Email content detected as spam",
        "DailyQuotaExceed": "Daily sending limit exceeded",
        "Throttling.User": "Sending too frequently, please wait a moment",
    }

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
    ) -> EmailSendResult:
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
            return EmailSendResult(True, "Email sent successfully")

        except Exception as err:
            error_code = None
            error_msg = str(err)
            
            if hasattr(err, 'data') and err.data:
                error_code = err.data.get('Code')
                error_msg = self.ERROR_MESSAGES.get(error_code, err.data.get('Message', error_msg))
                logger.error(f"[ALIBABA] Error details: {err.data}")
            
            logger.error(f"[ALIBABA] Error sending email to {to_email}: {err}")
            
            # Map Alibaba error codes to specific exceptions
            if error_code == "InvalidEmail.Malformed":
                raise EmailFormatError("Invalid email address format")
            elif error_code in ["InvalidEmail.NotExist", "InvalidDomain"]:
                raise EmailNotExistError("Email address does not exist or is unreachable")
            elif error_code == "ReceiverBlacklist":
                raise EmailBlacklistedError("Recipient email is blacklisted")
            elif error_code in ["DailyQuotaExceed", "Throttling.User"]:
                raise EmailRateLimitError("Rate limit exceeded, please try again later")
            elif error_code == "InvalidTemplate":
                raise EmailTemplateError("Email template error")
            elif error_code in ["InvalidSendMail", "SpamTooMuch"]:
                raise EmailSendFailedError(error_msg)
            else:
                raise EmailSendFailedError(f"Failed to send email: {error_msg}")


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
            raise EmailProviderError(f"Provider {provider_type.value} is not available")
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

    async def send_verification_email(self, email: str) -> str:
        """
        Send verification code email using Tencent Cloud (template-based).
        
        Returns:
            str: Success message
            
        Raises:
            EmailFormatError: If email format is invalid
            EmailNotExistError: If email doesn't exist
            EmailBlacklistedError: If email is blacklisted
            EmailRateLimitError: If rate limit is exceeded
            EmailTemplateError: If template error occurs
            EmailProviderError: If provider error occurs
            EmailSendFailedError: If sending fails for other reasons
        """
        # Validate email format first
        if not validate_email_format(email):
            logger.warning(f"[EMAIL] Invalid email format: {email}")
            raise EmailFormatError("Invalid email address format")

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
        result = await provider.send_email(
            to_email=email,
            subject="Email Verification Code",
            content="",  # Not used with template
            template_id=self.verification_template,
            template_data={"code": verification_code}
        )

        if result.success:
            self.redis.set(redis_key, verification_code, ex=self.code_expiry_seconds)
            self._log_email_action("Verification email sent successfully", email)
            return "Verification code sent successfully"
        else:
            # This should not happen since provider.send_email should raise exceptions
            # But keeping as fallback
            raise EmailSendFailedError(result.message)

    def verify_code(self, email: str, code: str) -> str:
        """
        Verify email code from Redis.
        
        Returns:
            str: Success message
            
        Raises:
            VerificationCodeExpiredError: If code has expired or doesn't exist
            VerificationCodeInvalidError: If code is invalid
        """
        redis_key = f"{self._VCODE_PREFIX}{email}"
        stored_code = self.redis.get(redis_key)

        self._log_email_action("Verifying code", email, provided=code, stored=stored_code)

        if not stored_code:
            raise VerificationCodeExpiredError("Verification code has expired or does not exist")
        
        if stored_code != code:
            raise VerificationCodeInvalidError("Invalid verification code")

        pipe = self.redis.pipeline()
        pipe.delete(redis_key)
        verified_key = f"{self._VERIFIED_PREFIX}{email}"
        pipe.set(verified_key, "true", ex=self.verified_status_expiry_seconds)
        pipe.execute()

        self._log_email_action("Code verification successful", email)
        return "Email verified successfully"

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
    @deprecated
    def _convert_full_result_to_template_data(full_result: Dict[str, Any]) -> Dict[str, str]:
        """Convert full result JSON to template data. Use for Tencent Template of ID 146629, Now it is deprecated."""
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

    async def send_astrology_result_email(
            self,
            email: str,
            astrology_result: str,
            subject: str,
            content_type: str = "html"
    ) -> Tuple[bool, str]:
        """
        Send astrology result email using Alibaba Cloud (HTML-based).
        
        Returns:
            Tuple[bool, str]: (success, error_message)
        """
        try:
            # Validate email format first
            if not validate_email_format(email):
                error_msg = "Invalid email address format"
                logger.warning(f"[EMAIL] {error_msg}: {email}")
                return False, error_msg

            provider = self.get_provider(self.result_provider)

            self._log_email_action(
                "Sending astrology result",
                email,
                provider=self.result_provider.value
            )

            # Use Alibaba's single send email for results
            result = await provider.send_email(
                to_email=email,
                subject=subject,
                content=astrology_result,
                content_type=content_type,
            )

            if result.success:
                self._log_email_action("Astrology result email sent successfully", email)
                return True, "Result email sent successfully"
            else:
                return False, result.message

        except json.JSONDecodeError as err:
            error_msg = "Failed to parse result data"
            logger.error(f"[EMAIL] Failed to parse astrology_result JSON: {err}")
            return False, error_msg
        except EmailProviderError as err:
            error_msg = str(err)
            logger.error(f"[EMAIL] Provider error: {error_msg}")
            return False, error_msg
        except Exception as err:
            error_msg = f"Failed to send result email: {str(err)}"
            logger.error(f"[EMAIL] Error sending result to {email}: {err}")
            return False, error_msg

    async def send_custom_email(
            self,
            to_email: str,
            subject: str,
            content: str,
            content_type: str = "html",
            provider: Optional[EmailProvider] = None,
            **kwargs
    ) -> Tuple[bool, str]:
        """
        Send a custom email using specified or default provider.
        
        Returns:
            Tuple[bool, str]: (success, error_message)
        """
        try:
            # Validate email format first
            if not validate_email_format(to_email):
                error_msg = "Invalid email address format"
                logger.warning(f"[EMAIL] {error_msg}: {to_email}")
                return False, error_msg

            # Use specified provider or default to Alibaba for general emails
            email_provider = provider if provider is not None else EmailProvider.ALIBABA
            provider_instance = self.get_provider(email_provider)

            self._log_email_action(
                "Sending custom email",
                to_email,
                subject=subject,
                provider=email_provider.value
            )

            result = await provider_instance.send_email(
                to_email=to_email,
                subject=subject,
                content=content,
                content_type=content_type,
                **kwargs
            )

            if result.success:
                self._log_email_action("Custom email sent successfully", to_email)
                return True, "Email sent successfully"
            else:
                return False, result.message

        except EmailProviderError as err:
            error_msg = str(err)
            logger.error(f"[EMAIL] Provider error: {error_msg}")
            return False, error_msg
        except Exception as err:
            error_msg = f"Failed to send email: {str(err)}"
            logger.error(f"[EMAIL] Error sending custom email to {to_email}: {err}")
            return False, error_msg
