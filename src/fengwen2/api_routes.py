import html
import json
import logging
import os
from datetime import datetime
from typing import Optional, Dict
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import HTMLResponse
from fastapi_cache import FastAPICache
from sqlalchemy.orm import Session

from src.fengwen2.admin_models import (
    Product, TranslationPair as DBTranslationPair,
    UserInfoRequest, EmailRequest, VerificationRequest, TranslationPairUpdate,
    TranslationPairRequest
)
from src.fengwen2.cache_config import CACHE_TTL, CacheManager
from src.fengwen2.database import get_db, AstrologyRecord
from src.fengwen2.service_manager import get_service_manager

logger = logging.getLogger(__name__)

router = APIRouter()

# Admin authentication
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")


def verify_admin_auth(authorization: Optional[str] = Header(None)):
    """Simple admin authentication"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        scheme, credentials = authorization.split()
        if scheme.lower() != "bearer" or credentials != ADMIN_PASSWORD:
            raise HTTPException(status_code=401, detail="Invalid authentication")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authentication format")


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
    except:
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


@router.post("/verify-email")
async def verify_email(
        request: VerificationRequest,
        db: Session = Depends(get_db),
        email_service=Depends(get_email_service),
        astrology_service=Depends(get_astrology_service)
):
    """Verify email and provide full results"""
    try:
        if not email_service.verify_code(request.email, request.code):
            raise HTTPException(status_code=400, detail="Invalid verification code")

        record = db.query(AstrologyRecord).filter(
            AstrologyRecord.email == request.email
        ).order_by(AstrologyRecord.created_at.desc()).first()

        if not record:
            raise HTTPException(status_code=404, detail="User record not found")

        response = await astrology_service.process_complete_astrology(record, db)
        return {
            "astrology_results": response["astrology_results"],
            "checkout_url": response["shopify_url"],
            "message": "Complete payment to receive your full reading via email."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in verify_email: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook/shopify")
async def shopify_webhook(
        request: Request,
        db: Session = Depends(get_db),
        shopify_service=Depends(get_shopify_service),
        email_service=Depends(get_email_service)
):
    """Handle Shopify payment webhooks with better error handling"""
    try:
        body = await request.body()
        signature = request.headers.get("X-Shopify-Hmac-Sha256", "")

        logger.info(f"[WEBHOOK] Received Shopify webhook")

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
                if record.is_purchased and record.shopify_order_id:
                    logger.info(f"[WEBHOOK] Order already processed for record {record_id}")
                    return {"status": "already_processed"}

                # update order status
                record.is_purchased = True
                record.shopify_order_id = str(webhook_data.get("id"))
                record.purchase_date = datetime.now()

                try:
                    db.commit()
                    logger.info(f"[WEBHOOK] Updated purchase status for record {record_id}")
                except Exception as e:
                    db.rollback()
                    logger.error(f"[WEBHOOK] Database error: {e}")
                    raise HTTPException(status_code=500, detail="Database error")

                # send the full result to user's email
                try:
                    email_sent = await email_service.send_astrology_result_email(record.email,
                                                                                 record.full_result_en or "Your personalized astrology reading is ready!")

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


@router.post("/admin/resend-result-email")
async def resend_result_email(
        request: Dict,
        db: Session = Depends(get_db),
        _: str = Depends(verify_admin_auth),
        email_service=Depends(get_email_service)
):
    """Manually resend result email for a record"""
    record_id = request.get("record_id")

    if not record_id:
        raise HTTPException(status_code=400, detail="record_id required")

    record = db.query(AstrologyRecord).filter(AstrologyRecord.id == record_id).first()

    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    if not record.is_purchased:
        raise HTTPException(status_code=400, detail="Record not purchased")

    try:
        email_sent = await email_service.send_astrology_result_email(record.email,
                                                                     record.full_result_en or "Your astrology reading")

        if email_sent:
            return {"message": f"Email sent to {record.email}"}
        else:
            raise HTTPException(status_code=500, detail="Failed to send email")

    except Exception as e:
        logger.error(f"Error resending email: {e}")
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


@router.get("/admin/admin-page")
async def get_admin_page(_: str = Depends(verify_admin_auth)):
    """Serve admin management page from template"""
    try:
        with open("templates/admin_page.html", "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Admin template not found")


@router.get("/admin/translations")
async def get_translations(db: Session = Depends(get_db), _: str = Depends(verify_admin_auth)):
    """Get all translation pairs"""
    translations = db.query(DBTranslationPair).all()
    return translations


@router.post("/admin/translations")
async def add_translation(translation: TranslationPairRequest, db: Session = Depends(get_db),
                          _: str = Depends(verify_admin_auth)):
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
                             _: str = Depends(verify_admin_auth)):
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

        # Cache the result
        await CacheManager.set_cached_result(cache_key, result, CACHE_TTL)
        logger.info(f"[API] Result cached for email: {user_info.email}")

        return result
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error in calculate_astrology: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/cache/invalidate")
async def invalidate_cache(
        request: Dict,
        _: str = Depends(verify_admin_auth)
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
async def get_cache_stats(_: str = Depends(verify_admin_auth)):
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
