import base64
import hashlib
import hmac
import json
import logging
import os
from typing import Optional, Dict
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()


class ShopifyPaymentService:
    """
    Shopify payment integration service supporting both standard and Plus accounts
    
    For standard accounts: Uses cart links and draft orders
    For Plus accounts: Can use Checkout API (set use_plus_features=True)
    """

    def __init__(self, use_plus_features: bool = None):
        # Admin API credentials
        self.access_token = os.getenv("SHOPIFY_ACCESS_TOKEN")  # 需要从 Shopify Admin 获取
        self.webhook_secret = os.getenv("SHOPIFY_WEBHOOK_SECRET")
        self.shop_domain = os.getenv("SHOPIFY_SHOP_DOMAIN", "fengculture.com")
        self.api_version = "2024-01"
        
        # 确定是否使用Plus功能
        if use_plus_features is not None:
            self.use_plus_features = use_plus_features
        else:
            self.use_plus_features = os.getenv("SHOPIFY_USE_PLUS_FEATURES", "false").lower() in ("true", "1", "yes")

        # Product variant ID - 需要从 Shopify 获取
        self.product_variant_id = os.getenv("SHOPIFY_PRODUCT_VARIANT_ID")

        # Base API URLs
        self.admin_api_url = f"https://{self.shop_domain}/admin/api/{self.api_version}"

        # Headers for API requests
        self.headers = {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json"
        }

    async def create_checkout_url(self, user_email: str, record_id: int) -> Optional[str]:
        """Create checkout URL - uses appropriate method based on account type"""
        try:
            if self.use_plus_features:
                # Plus账户可以使用Checkout API
                logger.info(f"Using Plus features for record {record_id}")
                checkout_url = await self._create_plus_checkout(user_email, record_id)
                if checkout_url:
                    return checkout_url
                logger.info(f"Plus checkout failed, falling back to cart link for record {record_id}")
            
            # 标准账户或Plus失败时使用购物车链接方案
            cart_url = await self._create_cart_link(user_email, record_id)
            if cart_url:
                return cart_url
            
            # 失败后回退到draft order
            logger.info(f"Cart link creation failed, falling back to draft order for record {record_id}")
            return await self._create_draft_order(user_email, record_id)
        except Exception as e:
            logger.error(f"Error creating checkout URL: {e}")
            return None
    
    async def create_draft_order_url(self, user_email: str, record_id: int) -> Optional[str]:
        """Create a draft order - fallback method without discount code support"""
        try:
            draft_order_url = await self._create_draft_order(user_email, record_id)
            return draft_order_url
        except Exception as e:
            logger.error(f"Error creating draft order URL: {e}")
            return None

    async def _create_cart_link(self, user_email: str, record_id: int) -> Optional[str]:
        """Create a cart link with metadata for standard Shopify accounts"""
        try:
            if not self.product_variant_id:
                logger.error("Product variant ID not configured")
                return None
            
            # 基础购物车链接格式: https://shop.myshopify.com/cart/variant_id:quantity
            base_cart_url = f"https://{self.shop_domain}/cart/{self.product_variant_id}:1"
            
            # 添加URL参数传递元数据
            params = {
                "record_id": str(record_id),
                "service": "astrology_reading",
                "customer_email": user_email,
                "note": f"Astrology Reading - Record ID: {record_id}"
            }
            
            # 构建完整的URL
            cart_url = f"{base_cart_url}?{urlencode(params)}"
            logger.info(f"Created cart link for record {record_id}: {cart_url}")
            return cart_url
            
        except Exception as e:
            logger.error(f"Error creating cart link: {e}")
            return f"https://{self.shop_domain}/cart/{self.product_variant_id}:1"


    async def _create_plus_checkout(self, user_email: str, record_id: int) -> Optional[str]:
        """Create a checkout session using Plus API (requires Shopify Plus)"""
        try:
            async with httpx.AsyncClient() as client:
                checkout_data = {
                    "checkout": {
                        "line_items": [
                            {
                                "variant_id": self.product_variant_id,
                                "quantity": 1,
                                "properties": [
                                    {"name": "record_id", "value": str(record_id)}
                                ]
                            }
                        ],
                        "email": user_email,
                        "note": f"Astrology Reading - Record ID: {record_id}",
                        "note_attributes": [
                            {"name": "record_id", "value": str(record_id)},
                            {"name": "service", "value": "astrology_reading"}
                        ],
                        "cart_attributes": {
                            "record_id": str(record_id),
                            "service": "astrology_reading"
                        },
                        "tags": f"astrology,record_{record_id}",
                        "allow_discount_codes": True
                    }
                }

                response = await client.post(
                    f"{self.admin_api_url}/checkouts.json",
                    headers=self.headers,
                    json=checkout_data
                )

                if response.status_code == 201:
                    checkout = response.json()["checkout"]
                    checkout_url = checkout.get("web_url")
                    logger.info(f"Created Plus checkout for record {record_id}: {checkout_url}")
                    return checkout_url
                else:
                    logger.error(f"Failed to create Plus checkout: {response.text}")
                    return None

        except Exception as e:
            logger.error(f"Error creating Plus checkout: {e}")
            return None

    async def _create_draft_order(self, user_email: str, record_id: int) -> Optional[str]:
        """Create a draft order with custom attributes"""
        try:
            async with httpx.AsyncClient() as client:
                draft_order_data = {
                    "draft_order": {
                        "line_items": [
                            {
                                "variant_id": self.product_variant_id,
                                "quantity": 1,
                                "properties": [
                                    {"name": "record_id", "value": str(record_id)}
                                ]
                            }
                        ],
                        "customer": {
                            "email": user_email
                        },
                        "note": f"Astrology Reading - Record ID: {record_id}",
                        "tags": f"astrology,record_{record_id}",
                        "note_attributes": [
                            {"name": "record_id", "value": str(record_id)},
                            {"name": "service", "value": "astrology_reading"}
                        ]
                    }
                }

                response = await client.post(
                    f"{self.admin_api_url}/draft_orders.json",
                    headers=self.headers,
                    json=draft_order_data
                )

                if response.status_code == 201:
                    draft_order = response.json()["draft_order"]
                    invoice_url = draft_order.get("invoice_url")
                    logger.info(f"Created draft order for record {record_id}: {invoice_url}")
                    return invoice_url
                else:
                    logger.error(f"Failed to create draft order: {response.text}")
                    return None

        except Exception as e:
            logger.error(f"Error creating draft order: {e}")
            return None

    def verify_webhook(self, data: bytes, signature: str) -> bool:
        """Verify Shopify webhook signature"""
        try:
            if not self.webhook_secret:
                logger.warning("Webhook secret not configured")
                return True

            calculated_hmac = base64.b64encode(
                hmac.new(
                    self.webhook_secret.encode('utf-8'),
                    data,
                    hashlib.sha256
                ).digest()
            ).decode('utf-8')

            is_valid = hmac.compare_digest(signature, calculated_hmac)
            if not is_valid:
                logger.warning(f"Invalid webhook signature. Expected: {calculated_hmac}, Got: {signature}")
            return is_valid

        except Exception as e:
            logger.error(f"Error verifying webhook: {e}")
            return False

    def extract_record_id_from_order(self, order_data: Dict) -> Optional[int]:
        """Extract astrology record ID from multiple possible locations"""
        try:
            record_id = None

            # 1. Check line item properties
            line_items = order_data.get("line_items", [])
            for item in line_items:
                properties = item.get("properties", [])
                for prop in properties:
                    if prop.get("name", "").lower() in ["record_id", "record id"]:
                        record_id = prop.get("value")
                        logger.info(f"Found record_id in line item properties: {record_id}")
                        break
                if record_id:
                    break

            # 2. Check note attributes
            if not record_id:
                note_attributes = order_data.get("note_attributes", [])
                for attr in note_attributes:
                    if attr.get("name", "").lower() == "record_id":
                        record_id = attr.get("value")
                        logger.info(f"Found record_id in note attributes: {record_id}")
                        break

            # 3. Check order note
            if not record_id:
                note = order_data.get("note", "")
                if "Record ID:" in note:
                    record_id = note.split("Record ID:")[1].strip().split()[0]
                    logger.info(f"Found record_id in order note: {record_id}")

            # 4. Check order tags
            if not record_id:
                tags = order_data.get("tags", "")
                if "record_" in tags:
                    for tag in tags.split(","):
                        if tag.strip().startswith("record_"):
                            record_id = tag.strip().replace("record_", "")
                            logger.info(f"Found record_id in tags: {record_id}")
                            break

            # 5. Check cart attributes (from checkout)
            if not record_id:
                cart_attributes = order_data.get("cart_attributes", {})
                record_id = cart_attributes.get("record_id")
                if record_id:
                    logger.info(f"Found record_id in cart attributes: {record_id}")

            # 6. Check customer attributes (alternative checkout location)
            if not record_id:
                customer = order_data.get("customer", {})
                if customer:
                    customer_note = customer.get("note", "")
                    if "record_" in customer_note:
                        import re
                        match = re.search(r'record_(\d+)', customer_note)
                        if match:
                            record_id = match.group(1)
                            logger.info(f"Found record_id in customer note: {record_id}")

            # 7. Check order attributes (another possible location)
            if not record_id:
                order_attributes = order_data.get("order_attributes", [])
                for attr in order_attributes:
                    if attr.get("name", "").lower() == "record_id":
                        record_id = attr.get("value")
                        logger.info(f"Found record_id in order attributes: {record_id}")
                        break

            if record_id:
                return int(record_id)
            else:
                logger.warning(f"Could not find record_id in order {order_data.get('id', 'unknown')}")
                logger.debug(f"Order data: {json.dumps(order_data, indent=2)}")
                return None

        except Exception as e:
            logger.error(f"Error extracting record ID: {e}")
            return None

    async def get_order_details(self, order_id: str) -> Optional[Dict]:
        """Get order details from Shopify"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.admin_api_url}/orders/{order_id}.json",
                    headers=self.headers
                )

                if response.status_code == 200:
                    return response.json()["order"]
                else:
                    logger.error(f"Failed to get order details: {response.text}")
                    return None

        except Exception as e:
            logger.error(f"Error getting order details: {e}")
            return None
