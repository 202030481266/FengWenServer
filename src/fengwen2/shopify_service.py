import os
import hmac
import hashlib
import base64
from typing import Optional, Dict
from datetime import datetime
import httpx
from dotenv import load_dotenv

load_dotenv()

class ShopifyPaymentService:
    """Shopify payment integration service"""
    
    def __init__(self):
        self.api_key = os.getenv("SHOPIFY_API_KEY")
        self.api_secret = os.getenv("SHOPIFY_API_SECRET")
        self.webhook_secret = os.getenv("SHOPIFY_WEBHOOK_SECRET")
        self.shop_domain = os.getenv("SHOPIFY_SHOP_DOMAIN")
        self.api_version = "2024-01"
        
        # Base API URL
        self.base_url = f"https://{self.shop_domain}/admin/api/{self.api_version}"
        
        # Headers for API requests
        self.headers = {
            "X-Shopify-Access-Token": self.api_key,
            "Content-Type": "application/json"
        }
    
    async def create_checkout_url(self, user_email: str, record_id: int) -> Optional[str]:
        """Create direct product checkout URL"""
        try:
            # Direct link to the specific Shopify product with custom attributes
            product_url = "https://fengculture.com/products/bazi-test-1"
            
            # Add custom parameters to track the order
            checkout_url = f"{product_url}?customer_email={user_email}&record_id={record_id}"
            
            return checkout_url
            
        except Exception as e:
            print(f"Error creating checkout URL: {e}")
            return None
    
    def verify_webhook(self, data: bytes, signature: str) -> bool:
        """Verify Shopify webhook signature"""
        try:
            expected_signature = base64.b64encode(
                hmac.new(
                    self.webhook_secret.encode('utf-8'),
                    data,
                    hashlib.sha256
                ).digest()
            ).decode('utf-8')
            
            return hmac.compare_digest(signature, expected_signature)
            
        except Exception as e:
            print(f"Error verifying webhook: {e}")
            return False
    
    async def get_order_details(self, order_id: str) -> Optional[Dict]:
        """Get order details from Shopify"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/orders/{order_id}.json",
                    headers=self.headers
                )
                
                if response.status_code == 200:
                    return response.json()["order"]
                else:
                    print(f"Failed to get order details: {response.text}")
                    return None
                    
        except Exception as e:
            print(f"Error getting order details: {e}")
            return None
    
    def extract_record_id_from_order(self, order_data: Dict) -> Optional[int]:
        """Extract astrology record ID from order properties or note"""
        try:
            # Method 1: Check line item properties (Shopify format)
            line_items = order_data.get("line_items", [])
            for item in line_items:
                properties = item.get("properties", [])
                for prop in properties:
                    prop_name = prop.get("name", "").lower()
                    if prop_name in ["record id", "record_id", "recordid"]:
                        return int(prop.get("value"))
            
            # Method 2: Check order note (fallback format)
            note = order_data.get("note", "")
            if "record_id:" in note:
                record_id_str = note.split("record_id:")[1].split()[0]
                return int(record_id_str)
                
            return None
            
        except Exception as e:
            print(f"Error extracting record ID: {e}")
            return None