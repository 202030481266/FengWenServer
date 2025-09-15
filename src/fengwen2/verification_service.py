import logging
import os
import random
import string
from typing import Optional

from src.fengwen2.email_service import get_redis_client, validate_email_format

logger = logging.getLogger(__name__)


class VerificationCodeExpiredError(Exception):
    """Verification code has expired"""
    pass


class VerificationCodeInvalidError(Exception):
    """Verification code is invalid"""
    pass


class VerificationService:
    """处理验证码生成、存储和验证的业务逻辑服务"""
    
    _VCODE_PREFIX = "vcode:"
    _VERIFIED_PREFIX = "verified:"

    def __init__(self):
        self.redis = get_redis_client()
        if not self.redis:
            raise ConnectionError("VerificationService cannot operate without a Redis connection.")
        
        # Load configuration
        self.code_expiry_seconds = int(os.getenv("VERIFICATION_CODE_EXPIRY_SECONDS", 300))
        self.verified_status_expiry_seconds = int(os.getenv("VERIFIED_STATUS_EXPIRY_SECONDS", 600))
        
        logger.info("VerificationService initialized successfully")

    @staticmethod
    def generate_verification_code(length: int = 6) -> str:
        """Generate random verification code."""
        return ''.join(random.choices(string.digits, k=length))

    def store_verification_code(self, email: str, code: str) -> None:
        """
        Store verification code in Redis.
        
        Args:
            email: Email address
            code: Verification code to store
        """
        if not validate_email_format(email):
            raise ValueError("Invalid email format")
            
        redis_key = f"{self._VCODE_PREFIX}{email}"
        self.redis.set(redis_key, code, ex=self.code_expiry_seconds)
        logger.info(f"[VERIFICATION] Code stored for {email}")

    def verify_code(self, email: str, code: str) -> str:
        """
        Verify email code from Redis.
        
        Args:
            email: Email address
            code: Verification code to verify
        
        Returns:
            str: Success message
            
        Raises:
            VerificationCodeExpiredError: If code has expired or doesn't exist
            VerificationCodeInvalidError: If code is invalid
        """
        if not validate_email_format(email):
            raise ValueError("Invalid email format")
            
        redis_key = f"{self._VCODE_PREFIX}{email}"
        stored_code = self.redis.get(redis_key)

        logger.info(f"[VERIFICATION] Verifying code for {email}")

        if not stored_code:
            raise VerificationCodeExpiredError("Verification code has expired or does not exist")
        
        if stored_code != code:
            raise VerificationCodeInvalidError("Invalid verification code")

        # Delete verification code and set verified status
        pipe = self.redis.pipeline()
        pipe.delete(redis_key)
        verified_key = f"{self._VERIFIED_PREFIX}{email}"
        pipe.set(verified_key, "true", ex=self.verified_status_expiry_seconds)
        pipe.execute()

        logger.info(f"[VERIFICATION] Code verification successful for {email}")
        return "Email verified successfully"

    def is_email_recently_verified(self, email: str) -> bool:
        """
        Check if email's verified status key exists in Redis.
        
        Args:
            email: Email address to check
            
        Returns:
            bool: True if email is recently verified, False otherwise
        """
        if not validate_email_format(email):
            return False
            
        verified_key = f"{self._VERIFIED_PREFIX}{email}"
        is_verified = self.redis.exists(verified_key) > 0

        logger.info(f"[VERIFICATION] Verification status check for {email}: {is_verified}")
        return is_verified

    def get_verification_code_for_testing(self, email: str) -> Optional[str]:
        """
        Get verification code from Redis for testing purposes.
        
        Args:
            email: Email address
            
        Returns:
            Optional[str]: Verification code if exists, None otherwise
        """
        if not validate_email_format(email):
            return None
            
        return self.redis.get(f"{self._VCODE_PREFIX}{email}")

    def clear_verification_data(self, email: str) -> None:
        """
        Clear all verification data for an email (both code and verified status).
        
        Args:
            email: Email address
        """
        if not validate_email_format(email):
            return
            
        pipe = self.redis.pipeline()
        pipe.delete(f"{self._VCODE_PREFIX}{email}")
        pipe.delete(f"{self._VERIFIED_PREFIX}{email}")
        pipe.execute()
        
        logger.info(f"[VERIFICATION] Cleared all verification data for {email}")
