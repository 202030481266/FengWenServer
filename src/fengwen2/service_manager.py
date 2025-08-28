import logging
from typing import Optional
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)


class ServiceManager:

    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ServiceManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            from .email_service import EmailService
            from .shopify_service import ShopifyPaymentService
            from .astrology_service import AstrologyService
            from .token_service import TokenService, ScreenshotService, ReportEmailService
            
            self.email_service = EmailService()
            self.shopify_service = ShopifyPaymentService()
            self.astrology_service = AstrologyService()
            self.token_service = TokenService()
            self.screenshot_service = ScreenshotService()
            self.report_email_service = ReportEmailService(self.email_service)
            self._cleanup_task: Optional[asyncio.Task] = None
            self._cleanup_interval = 3600  # 3600 seconds = 1 hours
            
            ServiceManager._initialized = True
            logger.info("ServiceManager initialized successfully")
    
    async def startup(self):
        logger.info("Starting up services...")
        try:
            await self.screenshot_service.initialize()
            logger.info("Screenshot service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize screenshot service: {e}")
        self._cleanup_task = asyncio.create_task(self._token_cleanup_loop())
        logger.info("Started background token cleanup task")

    async def shutdown(self):
        logger.info("Shutting down services...")
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                logger.info("Token cleanup task cancelled")
        try:
            await self.screenshot_service.close()
            logger.info("Screenshot service closed")
        except Exception as e:
            logger.error(f"Error closing screenshot service: {e}")
    
    async def _token_cleanup_loop(self):
        """后台清理任务"""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                self.token_service.cleanup_expired_tokens()
                logger.info(f"Cleaned up expired tokens at {datetime.now()}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in token cleanup: {e}")
    
    def get_email_service(self):
        return self.email_service
    
    def get_shopify_service(self):
        return self.shopify_service
    
    def get_astrology_service(self):
        return self.astrology_service
    
    def get_token_service(self):
        return self.token_service
    
    def get_screenshot_service(self):
        return self.screenshot_service
    
    def get_report_email_service(self):
        return self.report_email_service

# singleton pattern
service_manager = ServiceManager()

def get_service_manager() -> ServiceManager:
    return service_manager