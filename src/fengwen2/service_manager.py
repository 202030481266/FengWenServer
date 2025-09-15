import logging

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
            from src.fengwen2.email_service import EmailService
            from src.fengwen2.shopify_service import ShopifyPaymentService
            from src.fengwen2.astrology_service import AstrologyService
            from src.fengwen2.mjml_render_service import MJMLEmailService
            from src.fengwen2.verification_service import VerificationService

            self.email_service = EmailService()
            self.shopify_service = ShopifyPaymentService()
            self.astrology_service = AstrologyService()
            self.verification_service = VerificationService()
            self.mjml_render_service = MJMLEmailService(
                template_dir="templates",  # 模板目录
                mjml_options={
                    "minify": True,  # 压缩HTML
                    "beautify": False,  # 美化输出
                    "validation_level": "soft"  # 验证级别：strict, soft, skip
                }
            )

            ServiceManager._initialized = True
            logger.info("ServiceManager initialized successfully")

    async def startup(self):
        logger.info("Starting up services...")

    async def shutdown(self):
        logger.info("Shutting down services...")

    def get_email_service(self):
        return self.email_service

    def get_shopify_service(self):
        return self.shopify_service

    def get_astrology_service(self):
        return self.astrology_service

    def get_verification_service(self):
        return self.verification_service

    def get_mjml_service(self):
        return self.mjml_render_service


# singleton pattern
service_manager = ServiceManager()


def get_service_manager() -> ServiceManager:
    return service_manager
