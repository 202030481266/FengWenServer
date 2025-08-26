from datetime import datetime
from typing import Optional, Dict, Any
import json
import logging
from sqlalchemy.orm import Session

from .database import AstrologyRecord
from .calendar_converter import gregorian_to_lunar
from .astrology_api import AstrologyAPIClient
from .translation import TranslationService
from .shopify_service import ShopifyPaymentService

logger = logging.getLogger(__name__)

class AstrologyService:
    """Core business logic for astrology processing"""
    
    def __init__(self):
        self.astrology_client = AstrologyAPIClient()
        self.translation_service = TranslationService()
        self.shopify_service = ShopifyPaymentService()
    
    def create_record(self, email: str, name: str, birth_date: str, 
                     birth_time: str, gender: str, is_lunar: bool, db: Session) -> AstrologyRecord:
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
    
    async def generate_preview_results(self, record: AstrologyRecord, db: Session):
        """Generate and save preview results"""
        if record.preview_result_zh:
            return
            
        try:
            preview_result = await self.astrology_client.get_preview_result(
                record.name, record.gender, record.birth_date, record.birth_time
            )
            logger.info(f"[SERVICE] Preview result received: {preview_result is not None}")
            
            if preview_result and preview_result.get("errcode") == 0 and preview_result.get("data"):
                preview_result_en = await self.translation_service.extract_and_translate_astrology_result(
                    preview_result, record.name
                )
                
                if preview_result_en:
                    record.preview_result_zh = json.dumps(preview_result)
                    record.preview_result_en = json.dumps(preview_result_en)
                    db.commit()
                    logger.info(f"[SERVICE] Preview results saved successfully")
                    
        except Exception as e:
            logger.error(f"[SERVICE] Error generating preview results: {e}")
    
    async def generate_full_results(self, record: AstrologyRecord, db: Session):
        """Generate and save full results"""
        if record.full_result_zh:
            return
            
        try:
            full_results = await self.astrology_client.get_full_results(
                record.name, record.gender, record.birth_date, record.birth_time
            )
            logger.info(f"[SERVICE] Full results received: {full_results is not None}")
            
            valid_results = {}
            for api_name, api_result in full_results.items():
                if api_result and not api_result.get("error") and api_result.get("errcode") == 0:
                    valid_results[api_name] = api_result
            
            if valid_results:
                record.full_result_zh = json.dumps(valid_results)
                db.commit()
                logger.info(f"[SERVICE] Full results saved: {list(valid_results.keys())}")
                
        except Exception as e:
            logger.error(f"[SERVICE] Error generating full results: {e}")
    
    async def generate_english_translation(self, record: AstrologyRecord, db: Session):
        """Generate English translation for full results"""
        if record.full_result_en or not record.full_result_zh:
            return
            
        try:
            full_results = json.loads(record.full_result_zh)
            full_result_en = await self.translation_service.extract_and_translate_astrology_result(
                full_results, record.name
            )
            
            if full_result_en:
                record.full_result_en = json.dumps(full_result_en)
                db.commit()
                logger.info(f"[SERVICE] English translation saved successfully")
                
        except Exception as e:
            logger.error(f"[SERVICE] Error generating English translation: {e}")
    
    async def process_complete_astrology(self, record: AstrologyRecord, db: Session) -> Dict[str, Any]:
        """Complete astrology processing pipeline"""
        await self.generate_preview_results(record, db)
        await self.generate_full_results(record, db)
        await self.generate_english_translation(record, db)
        
        checkout_url = await self.shopify_service.create_checkout_url(record.email, record.id)
        
        return self.format_response(record, checkout_url)
    
    def format_response(self, record: AstrologyRecord, checkout_url: str) -> Dict[str, Any]:
        """Format API response based on available data"""
        response = {}
        
        # Get English results
        if record.full_result_en:
            try:
                result_data = json.loads(record.full_result_en)
                logger.info(f"[SERVICE] Using full English result")
            except json.JSONDecodeError:
                result_data = {"message": record.full_result_en}
        elif record.preview_result_en:
            try:
                result_data = json.loads(record.preview_result_en)
                logger.info(f"[SERVICE] Using preview English result")
            except json.JSONDecodeError:
                result_data = {"message": record.preview_result_en}
        else:
            result_data = {
                "base_info": {
                    "name": record.name,
                    "birth_date": record.birth_date.strftime('%Y-%m-%d'),
                    "birth_time": record.birth_time,
                    "gender": record.gender
                },
                "message": f"Dear {record.name}, your astrology reading is being processed.",
                "status": "processing"
            }
        
        response["astrology_results"] = result_data
        response["shopify_url"] = checkout_url or "https://example.com/checkout"
        
        # Add Chinese data if available
        chinese_data = None
        if record.full_result_zh:
            try:
                chinese_data = json.loads(record.full_result_zh)
            except json.JSONDecodeError:
                chinese_data = record.full_result_zh
        elif record.preview_result_zh:
            try:
                chinese_data = json.loads(record.preview_result_zh)
            except json.JSONDecodeError:
                chinese_data = record.preview_result_zh
        
        if chinese_data:
            response["chinese"] = chinese_data
        
        return response