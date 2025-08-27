import httpx
from datetime import datetime
from typing import Dict, Optional, Any
import os
import re
from dotenv import load_dotenv

load_dotenv()

ASTROLOGY_API_KEY = os.getenv("ASTROLOGY_API_KEY", "")


class AstrologyAPIClient:
    """Client for calling astrology APIs"""

    def __init__(self):
        self.api_key = ASTROLOGY_API_KEY
        self.headers = {"Content-Type": "application/x-www-form-urlencoded"}
        self.base_url = "https://api.yuanfenju.com/index.php/v1"

        # Image field patterns to filter out
        self.image_field_patterns = [
            r'.*img.*', r'.*image.*', r'.*pic.*', r'.*photo.*',
            r'.*avatar.*', r'.*thumb.*', r'.*icon.*', r'.*logo.*'
        ]

    def _filter_image_fields(self, data: Any) -> Any:
        """Recursively filter out image-related fields from API response"""
        if isinstance(data, dict):
            filtered_dict = {}
            for key, value in data.items():
                # Check if field name matches image patterns
                key_lower = key.lower()
                is_image_field = any(re.match(pattern, key_lower, re.IGNORECASE)
                                     for pattern in self.image_field_patterns)

                if is_image_field:
                    continue  # Skip image fields by name

                # Check if value looks like image data
                if isinstance(value, str) and self._is_image_data(value):
                    continue  # Skip image data by content

                # Recursively process nested data
                filtered_dict[key] = self._filter_image_fields(value)
            return filtered_dict
        elif isinstance(data, list):
            return [self._filter_image_fields(item) for item in data]
        else:
            return data

    def _is_image_data(self, value: str) -> bool:
        """Check if string value appears to be image data"""
        if not isinstance(value, str) or len(value) < 10:
            return False

        value_lower = value.lower()

        # Check for data URL images (including malformed ones like data:image/image/jpeg)
        if value_lower.startswith('data:image'):
            return True

        # Check for base64 image data (long strings that look like base64)
        if len(value) > 1000 and re.match(r'^[A-Za-z0-9+/]*={0,2}$', value):
            return True

        # Check for image URLs
        if (value_lower.startswith(('http://', 'https://')) and
                any(ext in value_lower for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg'])):
            return True

        return False

    async def _call_api(self, endpoint: str, name: str, gender: str, birth_date: datetime, birth_time: str) -> Dict:
        """Generic API caller for all astrology endpoints"""
        url = f"{self.base_url}/{endpoint}"
        hour, minute = birth_time.split(":")

        data = {
            "api_key": self.api_key,
            "name": name,
            "sex": "0" if gender.lower() == "male" else "1",
            "type": "1",
            "year": str(birth_date.year),
            "month": str(birth_date.month),
            "day": str(birth_date.day),
            "hours": hour,
            "minute": minute
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, headers=self.headers)
            raw_data = response.json()
            # Filter out image fields before returning
            return self._filter_image_fields(raw_data)

    async def call_bazi_api(self, name: str, gender: str, birth_date: datetime, birth_time: str) -> Dict:
        """Call Bazi calculation API"""
        return await self._call_api("Bazi/cesuan", name, gender, birth_date, birth_time)

    async def call_zhengyuan_api(self, name: str, gender: str, birth_date: datetime, birth_time: str) -> Dict:
        """Call True Love prediction API"""
        return await self._call_api("Yuce/zhengyuan", name, gender, birth_date, birth_time)

    async def call_liudao_api(self, name: str, gender: str, birth_date: datetime, birth_time: str) -> Dict:
        """Call Six Paths reincarnation API"""
        return await self._call_api("Yuce/liudaolunhui", name, gender, birth_date, birth_time)

    async def get_preview_result(self, name: str, gender: str, birth_date: datetime, birth_time: str) -> Optional[Dict]:
        """Get preview result (using Bazi API only as mentioned in requirements)"""
        try:
            result = await self.call_bazi_api(name, gender, birth_date, birth_time)
            return result
        except Exception as e:
            print(f"Error calling preview API: {e}")
            return None

    async def get_full_results(self, name: str, gender: str, birth_date: datetime, birth_time: str) -> Dict:
        """Get all three API results"""
        api_calls = {
            "bazi": self.call_bazi_api,
            "zhengyuan": self.call_zhengyuan_api,
            "liudao": self.call_liudao_api
        }

        results = {}
        for api_name, api_func in api_calls.items():
            try:
                results[api_name] = await api_func(name, gender, birth_date, birth_time)
            except Exception as e:
                results[api_name] = {"error": str(e)}

        return results