import json
import logging
import os
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Dict, Tuple

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


def validate_email_format(email: str) -> bool:
    """Basic email format validation"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


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
            elif err.code in ["RequestLimitExceeded.SendEmailRequestLimit", "FailedOperation.FrequencyLimit",
                              "FailedOperation.ExceedSendLimit"]:
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

    def __init__(self):
        # Initialize providers
        self.providers = {}
        self._init_providers()

        # Default providers for different email types
        # USE ALIBABA by default
        self.verification_provider = EmailProvider.ALIBABA
        self.result_provider = EmailProvider.ALIBABA

    def _init_providers(self):
        """Initialize email providers based on available credentials."""
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

    async def send_verification_email(
            self,
            email: str,
            content: str,
            content_type: str = "html",
            provider: Optional[EmailProvider] = None
    ) -> EmailSendResult:
        """
        Send verification code email using specified provider (template-based).
        
        Args:
            :param provider: Email provider to use (defaults to verification_provider)
            :param content: The verification code email to send
            :param email: Target email address
            :param content_type: Email content type: html or plain-text
        
        Returns:
            EmailSendResult: Result of the email sending operation
            
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

        email_provider = provider if provider is not None else self.verification_provider
        provider_instance = self.get_provider(email_provider)

        self._log_email_action(
            "Sending verification code",
            email,
            code="******",
            provider=email_provider.value
        )

        # Use template system for verification emails
        result = await provider_instance.send_email(
            to_email=email,
            subject="Email Verification Code",
            content=content,
            content_type=content_type
        )

        if result.success:
            self._log_email_action("Verification email sent successfully", email)

        return result

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
