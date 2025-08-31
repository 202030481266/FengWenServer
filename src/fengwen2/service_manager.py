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
            from .email_service import EmailService
            from .shopify_service import ShopifyPaymentService
            from .astrology_service import AstrologyService

            self.email_service = EmailService()
            self.shopify_service = ShopifyPaymentService()
            self.astrology_service = AstrologyService()

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


# singleton pattern
service_manager = ServiceManager()


def get_service_manager() -> ServiceManager:
    return service_manager
