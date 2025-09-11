import html
import json
import logging
import os
from typing import Optional, Dict
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi_cache import FastAPICache
from sqlalchemy.orm import Session

from src.fengwen2.admin_auth import get_current_admin_user
from src.fengwen2.admin_models import (
    Product, TranslationPair as DBTranslationPair,
    UserInfoRequest, EmailRequest, VerificationRequest, TranslationPairUpdate,
    TranslationPairRequest, CreatePaymentLinkRequest, PaymentLinkResponse
)
from src.fengwen2.astrology_data_mask import AstrologyDataMaskingService
from src.fengwen2.astrology_views import AstrologyApiResponseView, AstrologyResultsView
from src.fengwen2.cache_config import CACHE_TTL, CacheManager
from src.fengwen2.database import get_db, AstrologyRecord
from src.fengwen2.service_manager import get_service_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# Admin authentication dependency
def get_admin_user(admin: str = Depends(get_current_admin_user)):
    """Dependency to protect admin routes"""
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return admin


# Simple security functions
ALLOWED_DOMAINS = [
    "crystal-divination.com", "tarot-reading.com", "fengshui-guide.com",
    "example.com", "localhost", "127.0.0.1"
]


def validate_url(url: str) -> bool:
    """Simple URL validation to prevent open redirects"""
    if not url or url == "#":
        return True
    try:
        parsed = urlparse(url)
        if not parsed.scheme.startswith('http'):
            return False
        domain = parsed.netloc.split(':')[0]
        return any(domain.endswith(allowed) for allowed in ALLOWED_DOMAINS)
    except Exception as e:
        logger.error("Exception while validating URL: %s", e, exc_info=True)
        return False


def clean_text(text: str) -> str:
    """Clean text to prevent XSS"""
    if not text:
        return ""
    return html.escape(text.strip()[:200])


# use dependency injection
def get_email_service():
    return get_service_manager().get_email_service()


def get_shopify_service():
    return get_service_manager().get_shopify_service()


def get_astrology_service():
    return get_service_manager().get_astrology_service()


def get_mjml_service():
    return get_service_manager().get_mjml_service()


@router.post("/submit-info")
async def submit_user_info(
        user_info: UserInfoRequest,
        db: Session = Depends(get_db),
        astrology_service=Depends(get_astrology_service)
):
    """Submit user info and get preview result"""
    logger.info(f"[API] User info submission started for email: {user_info.email}")
    try:
        record = astrology_service.create_record(user_info.email, user_info.name, user_info.birth_date,
                                                 user_info.birth_time, user_info.gender, db)

        return {
            "record_id": record.id,
            "lunar_date": record.lunar_date,
            "preview_result": "Your personalized reading is being prepared...",
            "message": "Please verify your email to see complete results."
        }

    except Exception as e:
        logger.error(f"Error in submit_user_info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send-verification")
async def send_verification_code(
        request: EmailRequest,
        email_service=Depends(get_email_service)
):
    """Send email verification code"""
    try:
        verification_code = await email_service.send_verification_email(request.email)
        if verification_code:
            return {"message": "Verification code sent to your email"}
        else:
            raise HTTPException(status_code=500, detail="Failed to send verification code")
    except Exception as e:
        logger.error(f"Error sending verification: {e}")
        raise HTTPException(status_code=500, detail="Failed to send verification code")


@router.post("/webhook/shopify")
async def shopify_webhook(
        request: Request,
        db: Session = Depends(get_db),
        shopify_service=Depends(get_shopify_service),
        email_service=Depends(get_email_service),
        mjml_service=Depends(get_mjml_service)
):
    """Handle Shopify payment webhooks with better error handling"""
    try:
        body = await request.body()
        signature = request.headers.get("X-Shopify-Hmac-Sha256", "")

        logger.info(f"[WEBHOOK] Received Shopify webhook")

        # verify the url is sent from shopify
        if os.getenv("ENVIRONMENT") == "production":
            if not shopify_service.verify_webhook(body, signature):
                logger.error("[WEBHOOK] Invalid webhook signature")
                raise HTTPException(status_code=401, detail="Invalid signature")

        webhook_data = json.loads(body)
        webhook_topic = request.headers.get("X-Shopify-Topic", "")

        logger.info(f"[WEBHOOK] Topic: {webhook_topic}, Order ID: {webhook_data.get('id')}")

        if webhook_topic not in ["orders/paid", "orders/fulfilled", "orders/create"]:
            logger.info(f"[WEBHOOK] Ignoring webhook topic: {webhook_topic}")
            return {"status": "ignored"}

        # extract the record ID
        record_id = shopify_service.extract_record_id_from_order(webhook_data)

        if not record_id:
            customer_email = webhook_data.get("email") or webhook_data.get("customer", {}).get("email")

            if customer_email:
                logger.info(f"[WEBHOOK] Trying to find record by email: {customer_email}")
                record = db.query(AstrologyRecord).filter(
                    AstrologyRecord.email == customer_email,
                    AstrologyRecord.is_purchased == False
                ).order_by(AstrologyRecord.created_at.desc()).first()

                if record:
                    record_id = record.id
                    logger.info(f"[WEBHOOK] Found record by email: {record_id}")

        if record_id:
            record = db.query(AstrologyRecord).filter(AstrologyRecord.id == record_id).first()

            if record:
                new_order_id = str(webhook_data.get("id"))

                # 防止重复发送邮件
                if record.shopify_order_id == new_order_id:
                    logger.info(f"[WEBHOOK] Order {new_order_id} has already been processed for record {record_id}")
                    return {"status": "already_processed_duplicate_webhook"}

                record.is_purchased = True
                record.shopify_order_id = new_order_id  # update the order_id

                try:
                    db.commit()
                    logger.info(f"[WEBHOOK] Updated purchase status for record {record_id}")
                except Exception as e:
                    db.rollback()
                    logger.error(f"[WEBHOOK] Database error: {e}")
                    raise HTTPException(status_code=500, detail="Database error")

                # send the full result to user's email
                try:
                    full_result_en = json.loads(str(record.full_result_en))
                    astrology_result = AstrologyResultsView.model_validate(full_result_en)

                    # pick the email template
                    advantage_element = astrology_result.bazi.data.xiyongshen.rizhu_tiangan
                    if advantage_element == '水' or advantage_element.lower() == 'water':
                        email_template = 'astrology_report_water.mjml.j2'
                    elif advantage_element == '火' or advantage_element.lower() == 'fire':
                        email_template = 'astrology_report_fire.mjml.j2'
                    elif advantage_element == '金' or advantage_element.lower() == 'metal':
                        email_template = 'astrology_report_metal.mjml.j2'
                    elif advantage_element == '木' or advantage_element.lower() == 'wood':
                        email_template = 'astrology_report_wood.mjml.j2'
                    else:
                        email_template = 'astrology_report_earth.mjml.j2'

                    # render the result
                    email_content = mjml_service.render_email(
                        template_name=email_template,
                        astrology_results=astrology_result
                    )

                    email_sent = await email_service.send_astrology_result_email(
                        email=record.email,
                        astrology_result=email_content,
                        subject='Your Astrology Report',
                        content_type='html'
                    )

                    if email_sent:
                        logger.info(f"[WEBHOOK] Result email sent to {record.email}")
                    else:
                        logger.error(f"[WEBHOOK] Failed to send email to {record.email}")

                except Exception as e:
                    logger.error(f"[WEBHOOK] Email service error: {e}")

            else:
                logger.error(f"[WEBHOOK] Record {record_id} not found in database")
        else:
            logger.error(f"[WEBHOOK] Could not identify record for order {webhook_data.get('id')}")

        return {"status": "success"}

    except json.JSONDecodeError as e:
        logger.error(f"[WEBHOOK] Invalid JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        logger.error(f"[WEBHOOK] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Public products endpoint for frontend
@router.get("/products")
async def get_products(db: Session = Depends(get_db)):
    """Get all products, ensure we have exactly 3"""
    products = db.query(Product).all()

    # Ensure we have exactly 3 products
    while len(products) < 3:
        new_product = Product(
            name=f"Product {len(products) + 1}",
            image_url="https://via.placeholder.com/300x200",
            redirect_url="#"
        )
        db.add(new_product)
        products.append(new_product)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create products")

    # Return serialized products with clean data
    result = []
    for product in products[:3]:
        result.append({
            "id": product.id,
            "name": clean_text(product.name or ""),
            "image_url": clean_text(product.image_url or ""),
            "redirect_url": product.redirect_url if validate_url(product.redirect_url) else "#"
        })

    return result  # Return only first 3


@router.get("/admin/translations")
async def get_translations(db: Session = Depends(get_db), _: str = Depends(get_admin_user)):
    """Get all translation pairs"""
    translations = db.query(DBTranslationPair).all()
    return translations


@router.post("/admin/translations")
async def add_translation(translation: TranslationPairRequest, db: Session = Depends(get_db),
                          _: str = Depends(get_admin_user)):
    """Add translation pair"""
    new_translation = DBTranslationPair(
        chinese_text=clean_text(translation.chinese_text),
        english_text=clean_text(translation.english_text)
    )
    db.add(new_translation)
    try:
        db.commit()
        return {"message": "Translation pair added"}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to add translation")


@router.put("/admin/translations/{translation_id}")
async def update_translation(translation_id: int, translation: TranslationPairUpdate, db: Session = Depends(get_db),
                             _: str = Depends(get_admin_user)):
    """Update translation pair"""
    existing = db.query(DBTranslationPair).filter(DBTranslationPair.id == translation_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Translation not found")

    existing.chinese_text = clean_text(translation.chinese_text)
    existing.english_text = clean_text(translation.english_text)
    try:
        db.commit()
        return {"message": "Translation updated"}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update translation")


@router.post("/verify-email-first")
async def verify_email_first(
        request: VerificationRequest,
        email_service=Depends(get_email_service)
):
    logger.info(f"[API] Email verification started for: {request.email}")

    if not email_service.verify_code(request.email, request.code):
        logger.warning(f"[API] Invalid verification code for email: {request.email}")
        raise HTTPException(status_code=400, detail="Invalid verification code")

    logger.info(f"[API] Email verification successful for: {request.email}")
    return {"message": "Email verified successfully", "verified": True}


@router.post("/astrology/calculate")
async def calculate_astrology(
        user_info: UserInfoRequest,
        db: Session = Depends(get_db),
        email_service=Depends(get_email_service),
        astrology_service=Depends(get_astrology_service)
):
    logger.info(f"[API] Astrology calculation started for email: {user_info.email}")

    if not email_service.is_email_recently_verified(user_info.email):
        logger.warning(f"[API] Email not verified or expired for: {user_info.email}")
        raise HTTPException(status_code=400, detail="Please verify your email first")

    # cache mechanism
    cache_key = CacheManager.generate_astrology_cache_key(user_info)
    cached_result = await CacheManager.get_cached_result(cache_key)
    if cached_result:
        logger.info(f"[API] Returning cached result for email: {user_info.email}")
        return cached_result

    try:
        record = astrology_service.create_record(user_info.email, user_info.name, user_info.birth_date,
                                                 user_info.birth_time, user_info.gender, db)

        result = await astrology_service.process_complete_astrology(record, db)
        result['record_id'] = record.id

        validated_data = AstrologyApiResponseView.model_validate(result)
        masked_data_model = AstrologyDataMaskingService.mask_astrology_response(
            validated_data,
            mask_liudao=True,
            mask_zhengyuan=True,
        )

        final_response_dict = masked_data_model.model_dump()
        await CacheManager.set_cached_result(cache_key, final_response_dict, CACHE_TTL)
        logger.info(f"[API] Preview result cached for email: {user_info.email}")

        return final_response_dict
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error in calculate_astrology: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/astrology/create-payment-link", response_model=PaymentLinkResponse)
async def create_payment_link(
        request_data: CreatePaymentLinkRequest,
        db: Session = Depends(get_db),
        shopify_service=Depends(get_shopify_service)
):
    """
    为给定的记录ID创建一个新的Shopify支付链接。
    当前端用户点击“解锁”按钮时，应该调用此接口。
    """
    logger.info(f"[API] Payment link creation requested for record_id: {request_data.record_id}")

    record = db.query(AstrologyRecord).filter(AstrologyRecord.id == request_data.record_id).first()

    if not record:
        logger.error(f"[API] Record not found for id: {request_data.record_id}")
        raise HTTPException(status_code=404, detail="Astrology record not found.")

    try:
        checkout_url = await shopify_service.create_checkout_url(record.email, record.id)
        if not checkout_url:
            logger.error(f"Failed to create Shopify checkout URL for record_id: {record.id}")
            raise HTTPException(status_code=500, detail="Could not create payment link. Please try again later.")

        logger.info(f"[API] Successfully created payment link for record_id: {record.id}")
        return {"shopify_url": checkout_url}

    except Exception as e:
        logger.error(f"Error in create_payment_link for record_id {request_data.record_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while creating the payment link.")


@router.post("/admin/cache/invalidate")
async def invalidate_cache(
        request: Dict,
        _: str = Depends(get_admin_user)
):
    """Invalidate cache for a specific email or all cache"""
    email = request.get("email")
    clear_all = request.get("clear_all", False)

    try:
        if clear_all:
            await CacheManager.clear_all_cache()
            return {"message": "All cache cleared"}
        elif email:
            await CacheManager.invalidate_user_cache(email)
            return {"message": f"Cache cleared for {email}"}
        else:
            raise HTTPException(status_code=400, detail="Provide email or set clear_all=true")
    except Exception as e:
        logger.error(f"Error managing cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/cache/stats")
async def get_cache_stats(_: str = Depends(get_admin_user)):
    """Get Redis cache statistics"""
    try:
        backend = FastAPICache.get_backend()
        info = await backend.redis.info("stats")
        dbsize = await backend.redis.dbsize()

        # Count astrology cache keys
        astrology_keys = 0
        async for _ in backend.redis.scan_iter(match="astrology-cache:*"):
            astrology_keys += 1

        return {
            "total_keys": dbsize,
            "astrology_cache_keys": astrology_keys,
            "hits": info.get("keyspace_hits", 0),
            "misses": info.get("keyspace_misses", 0),
            "hit_rate": round(info.get("keyspace_hits", 0) /
                              (info.get("keyspace_hits", 0) + info.get("keyspace_misses", 1)) * 100, 2)
        }
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
