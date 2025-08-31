import json
import logging
from datetime import datetime
from typing import Dict, Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.fengwen2.astrology_api import AstrologyAPIClient
from src.fengwen2.astrology_types import *
from src.fengwen2.astrology_views import *
from src.fengwen2.calendar_converter import gregorian_to_lunar
from src.fengwen2.database import AstrologyRecord
from src.fengwen2.shopify_service import ShopifyPaymentService
from src.fengwen2.translation import TranslationService

logger = logging.getLogger(__name__)


class AstrologyService:
    """Core business logic for astrology processing"""

    def __init__(self):
        self.astrology_client = AstrologyAPIClient()
        self.translation_service = TranslationService()
        self.shopify_service = ShopifyPaymentService()

    @staticmethod
    def create_record(email: str, name: str, birth_date: str, birth_time: str, gender: str,
                      db: Session) -> AstrologyRecord:
        """Create database record"""
        birth_date_obj = datetime.strptime(birth_date, "%Y-%m-%d")
        lunar_date = gregorian_to_lunar(birth_date_obj)

        record = AstrologyRecord(
            email=email,
            name=name,
            birth_date=birth_date_obj,
            birth_time=birth_time,
            gender=gender,
            lunar_date=lunar_date,
            created_at=datetime.now()
        )

        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    async def generate_full_results(self, record: AstrologyRecord, db: Session):
        """Generate and save full results"""
        if record.full_result_zh:
            return

        try:
            full_results = await self.astrology_client.get_full_results(
                record.name, record.gender, record.birth_date, record.birth_time
            )
            logger.info(f"[SERVICE] Full results received: {full_results is not None}")

            # 检验返回的数据是否正确，以及裁剪json数据
            AstrologyResults.model_validate(full_results)
            full_model = AstrologyResultsView.model_validate(full_results)
            full_results = full_model.model_dump()

            valid_results = {}
            for api_name, api_result in full_results.items():
                if api_result and not api_result.get("error") and api_result.get("errcode") == 0:
                    valid_results[api_name] = api_result

            if valid_results:
                record.full_result_zh = json.dumps(valid_results)
                db.commit()
                logger.info(f"[SERVICE] Full results saved: {list(valid_results.keys())}")
        except ValidationError as e:
            error_summary = "; ".join([f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()])
            logger.error(f"[VALIDATION ERROR] Summary: {error_summary}", exc_info=True)
        except Exception as e:
            logger.error(f"[SERVICE] Error generating full results: {e}", exc_info=True)

    async def generate_english_translation(self, record: AstrologyRecord, db: Session):
        """Generate English translation for full results"""
        if record.full_result_en or not record.full_result_zh:
            return

        try:
            full_results = json.loads(record.full_result_zh)
            full_result_en = await self.translation_service.extract_and_translate_astrology_result(full_results)

            if full_result_en:
                record.full_result_en = json.dumps(full_result_en)
                db.commit()
                logger.info(f"[SERVICE] English translation saved successfully")

        except Exception as e:
            logger.error(f"[SERVICE] Error generating English translation: {e}", exc_info=True)

    async def process_complete_astrology(self, record: AstrologyRecord, db: Session) -> Dict[str, Any]:
        """Complete astrology processing pipeline"""
        await self.generate_full_results(record, db)
        await self.generate_english_translation(record, db)
        db.refresh(record)  # refresh to get the latest data
        checkout_url = await self.shopify_service.create_checkout_url(record.email, record.id)
        return self.format_response(record, checkout_url)

    @staticmethod
    def format_response(record: AstrologyRecord, checkout_url: str) -> Dict[str, Any]:
        """Format API response based on available data"""
        if not record.full_result_en:
            logger.error(f"[SERVICE] No English translation available for record ID: {record.id}", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="Astrology reading is still being processed. Please try again later."
            )

        try:
            astrology_results = json.loads(record.full_result_en)
            logger.info(f"[SERVICE] Successfully loaded English results for record ID: {record.id}")
        except json.JSONDecodeError as e:
            logger.error(f"[SERVICE] Failed to parse English results for record ID: {record.id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Error processing astrology results. Please contact support."
            )

        # logically, full_result_zh should exist
        chinese_data = None
        if record.full_result_zh:
            try:
                chinese_data = json.loads(record.full_result_zh)
                logger.info(f"[SERVICE] Successfully loaded Chinese results for record ID: {record.id}")
            except json.JSONDecodeError as e:
                logger.warning(f"[SERVICE] Failed to parse Chinese results for record ID: {record.id}: {e}")
                chinese_data = None

        # full response
        response = {
            "astrology_results": astrology_results,
            "shopify_url": checkout_url or "https://example.com/checkout"
        }

        if chinese_data:
            response["chinese"] = chinese_data

        return response
