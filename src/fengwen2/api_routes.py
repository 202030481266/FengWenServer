import html
import json
import logging
import os
from datetime import datetime
from typing import Dict, List
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, File, UploadFile, status
from fastapi_cache import FastAPICache
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.fengwen2.admin_auth import get_current_admin_user
from src.fengwen2.admin_models import (
    Product, TranslationPair as DBTranslationPair,
    UserInfoRequest, EmailRequest, VerificationRequest, TranslationPairUpdate,
    TranslationPairRequest, CreatePaymentLinkRequest, PaymentLinkResponse, ProductUpdate
)
from src.fengwen2.astrology_data_mask import AstrologyDataMaskingService
from src.fengwen2.astrology_views import AstrologyApiResponseView, AstrologyResultsView
from src.fengwen2.cache_config import CACHE_TTL, CacheManager
from src.fengwen2.database import get_db, AstrologyRecord
from src.fengwen2.service_manager import get_service_manager

logger = logging.getLogger(__name__)

router = APIRouter()

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
        return True
    except Exception as e:
        logger.error("Exception while validating URL: %s", e, exc_info=True)
        return False


def require_admin_auth(request: Request):
    """管理员认证依赖"""
    current_user = get_current_admin_user(request)
    if not current_user:
        raise HTTPException(
            status_code=401,
            detail="需要管理员认证"
        )
    return current_user


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
    """Send email verification code with detailed error handling"""
    try:
        success, message = await email_service.send_verification_email(request.email)

        if success:
            return {"success": True, "message": message}
        else:
            if "Invalid email" in message or "format" in message.lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "INVALID_EMAIL", "message": message}
                )
            elif "does not exist" in message or "unreachable" in message:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "EMAIL_NOT_EXIST", "message": message}
                )
            elif "blacklist" in message.lower():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error": "EMAIL_BLACKLISTED", "message": message}
                )
            elif "limit" in message.lower() or "frequently" in message.lower():
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={"error": "RATE_LIMIT", "message": message}
                )
            elif "template" in message.lower():
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={"error": "TEMPLATE_ERROR", "message": "Email service configuration error"}
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={"error": "SEND_FAILED", "message": message}
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in send_verification_code: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": "An unexpected error occurred. Please try again later."}
        )


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


@router.put("/admin/products/{product_id}")
async def update_product(
        request: Request,
        product_id: int,
        product_update: ProductUpdate,
        db: Session = Depends(get_db),
        _: str = Depends(require_admin_auth)
):
    """更新产品信息"""
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        # 更新非空字段
        if product_update.name is not None:
            product.name = clean_text(product_update.name)
        if product_update.image_url is not None:
            product.image_url = clean_text(product_update.image_url)
        if product_update.redirect_url is not None:
            # 验证URL安全性
            if validate_url(product_update.redirect_url):
                product.redirect_url = product_update.redirect_url
            else:
                raise HTTPException(status_code=400, detail="Invalid redirect URL")

        db.commit()
        db.refresh(product)

        return {
            "id": product.id,
            "name": product.name,
            "image_url": product.image_url,
            "redirect_url": product.redirect_url,
            "message": "Product updated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating product {product_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update product")


@router.delete("/admin/products/{product_id}")
async def delete_product(
        request: Request,
        product_id: int,
        db: Session = Depends(get_db),
        _: str = Depends(require_admin_auth)
):
    """删除产品 - 注意：由于系统需要保持3个产品，删除后会自动创建新的空产品"""
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        db.delete(product)

        # 确保始终有3个产品，如果不够的话就会自动创建空的产品
        product_count = db.query(Product).count()
        if product_count < 3:
            new_product = Product(
                name=f"Product {product_count + 1}",
                image_url="https://via.placeholder.com/300x200",
                redirect_url="#"
            )
            db.add(new_product)

        db.commit()
        return {"message": "Product deleted successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting product {product_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete product")


@router.post("/admin/products")
async def create_product(
        request: Request,
        product: ProductUpdate,
        db: Session = Depends(get_db),
        _: str = Depends(require_admin_auth)
):
    """创建新产品"""
    try:
        # 检查产品数量，如果大于3个的话那就要删除其中的一些
        product_count = db.query(Product).count()
        if product_count >= 3:
            raise HTTPException(
                status_code=400,
                detail="Maximum number of products (3) reached. Please delete a product first."
            )

        new_product = Product(
            name=clean_text(product.name or "New Product"),
            image_url=clean_text(product.image_url or "https://via.placeholder.com/300x200"),
            redirect_url=product.redirect_url if validate_url(product.redirect_url) else "#"
        )

        db.add(new_product)
        db.commit()
        db.refresh(new_product)

        return {
            "id": new_product.id,
            "name": new_product.name,
            "image_url": new_product.image_url,
            "redirect_url": new_product.redirect_url
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating product: {e}")
        raise HTTPException(status_code=500, detail="Failed to create product")


@router.get("/admin/translations")
async def get_translations(
        request: Request,
        db: Session = Depends(get_db),
        _: str = Depends(require_admin_auth)
):
    """Get all translation pairs"""
    translations = db.query(DBTranslationPair).all()
    return translations


@router.post("/admin/translations")
async def add_translation(
        request: Request,
        translation: TranslationPairRequest,
        db: Session = Depends(get_db),
        _: str = Depends(require_admin_auth)
):
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
async def update_translation(
        request: Request,
        translation_id: int,
        translation: TranslationPairUpdate,
        db: Session = Depends(get_db),
        _: str = Depends(require_admin_auth)
):
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


@router.delete("/admin/translations/{translation_id}")
async def delete_translation(
        request: Request,
        translation_id: int,
        db: Session = Depends(get_db),
        _: str = Depends(require_admin_auth)
):
    """删除翻译对"""
    try:
        translation = db.query(DBTranslationPair).filter(
            DBTranslationPair.id == translation_id
        ).first()

        if not translation:
            raise HTTPException(status_code=404, detail="Translation not found")

        db.delete(translation)
        db.commit()

        return {"message": "Translation deleted successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting translation {translation_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete translation")


@router.get("/admin/translations/{translation_id}")
async def get_translation(
        request: Request,
        translation_id: int,
        db: Session = Depends(get_db),
        _: str = Depends(require_admin_auth)
):
    """获取单个翻译对详情"""
    translation = db.query(DBTranslationPair).filter(
        DBTranslationPair.id == translation_id
    ).first()

    if not translation:
        raise HTTPException(status_code=404, detail="Translation not found")

    return {
        "id": translation.id,
        "chinese_text": translation.chinese_text,
        "english_text": translation.english_text
    }


@router.post("/admin/translations/batch")
async def add_batch_translations(
        request: Request,
        translations: List[TranslationPairRequest],
        db: Session = Depends(get_db),
        _: str = Depends(require_admin_auth)
):
    """批量添加翻译对"""
    try:
        added_translations = []
        for translation in translations:
            new_translation = DBTranslationPair(
                chinese_text=clean_text(translation.chinese_text),
                english_text=clean_text(translation.english_text)
            )
            db.add(new_translation)
            added_translations.append(new_translation)

        db.commit()

        return {
            "message": f"Successfully added {len(added_translations)} translations",
            "count": len(added_translations)
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error adding batch translations: {e}")
        raise HTTPException(status_code=500, detail="Failed to add translations")


@router.post("/verify-email-first")
async def verify_email_first(
        request: VerificationRequest,
        email_service=Depends(get_email_service)
):
    logger.info(f"[API] Email verification started for: {request.email}")
    try:
        success, message = email_service.verify_code(request.email, request.code)

        if success:
            logger.info(f"[API] Email verification successful for: {request.email}")
            return {"success": True, "message": message}
        else:
            if "expired" in message.lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "CODE_EXPIRED", "message": message}
                )
            elif "invalid" in message.lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "INVALID_CODE", "message": message}
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "VERIFICATION_FAILED", "message": message}
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in verify_email_code: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": "An unexpected error occurred. Please try again later."}
        )


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
        req: Request,
        request: Dict,
        _: str = Depends(require_admin_auth)
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
async def get_cache_stats(
        request: Request,
        _: str = Depends(require_admin_auth)
):
    """Get Redis cache statistics"""
    try:
        backend = FastAPICache.get_backend()
        info = await backend.redis.info("stats")
        db_size = await backend.redis.dbsize()

        # Count astrology cache keys
        astrology_keys = 0
        async for _ in backend.redis.scan_iter(match="astrology-cache:*"):
            astrology_keys += 1

        return {
            "total_keys": db_size,
            "astrology_cache_keys": astrology_keys,
            "hits": info.get("keyspace_hits", 0),
            "misses": info.get("keyspace_misses", 0),
            "hit_rate": round(info.get("keyspace_hits", 0) /
                              (info.get("keyspace_hits", 0) + info.get("keyspace_misses", 1)) * 100, 2)
        }
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/send-email/{record_id}")
async def test_send_email(
        record_id: str,
        db: Session = Depends(get_db),
        email_service=Depends(get_email_service),
        mjml_service=Depends(get_mjml_service)
):
    """测试邮件发送功能 - 仅用于开发环境"""
    try:
        # 安全检查：仅在非生产环境下可用
        if os.getenv("ENVIRONMENT") == "production":
            raise HTTPException(
                status_code=403,
                detail="This endpoint is not available in production"
            )

        logger.info(f"[TEST EMAIL] Starting email test for record: {record_id}")

        # 查询记录
        record = db.query(AstrologyRecord).filter(
            AstrologyRecord.id == record_id
        ).first()

        if not record:
            logger.error(f"[TEST EMAIL] Record {record_id} not found")
            raise HTTPException(status_code=404, detail=f"Record {record_id} not found")

        # 检查是否有完整结果
        if not record.full_result_en:
            logger.error(f"[TEST EMAIL] No full_result_en for record {record_id}")
            raise HTTPException(
                status_code=400,
                detail="Record does not have full_result_en"
            )

        try:
            full_result_en = json.loads(str(record.full_result_en))
            astrology_result = AstrologyResultsView.model_validate(full_result_en)

            # 获取有利元素以选择邮件模板
            advantage_element = astrology_result.bazi.data.xiyongshen.rizhu_tiangan
            logger.info(f"[TEST EMAIL] Advantage element: {advantage_element}")

            # 根据元素选择邮件模板
            email_template_map = {
                '水': 'astrology_report_water.mjml.j2',
                'water': 'astrology_report_water.mjml.j2',
                '火': 'astrology_report_fire.mjml.j2',
                'fire': 'astrology_report_fire.mjml.j2',
                '金': 'astrology_report_metal.mjml.j2',
                'metal': 'astrology_report_metal.mjml.j2',
                '木': 'astrology_report_wood.mjml.j2',
                'wood': 'astrology_report_wood.mjml.j2',
            }

            # 获取模板，默认使用 earth
            email_template = email_template_map.get(
                advantage_element.lower() if advantage_element else '',
                'astrology_report_earth.mjml.j2'
            )

            logger.info(f"[TEST EMAIL] Using template: {email_template}")

            # 渲染邮件内容
            email_content = mjml_service.render_email(
                template_name=email_template,
                astrology_results=astrology_result
            )

            # 发送邮件
            email_sent = await email_service.send_astrology_result_email(
                email=record.email,
                astrology_result=email_content,
                subject='[TEST] Your Astrology Report',
                content_type='html'
            )

            if email_sent:
                logger.info(f"[TEST EMAIL] Email successfully sent to {record.email}")
                return {
                    "status": "success",
                    "message": f"Test email sent to {record.email}",
                    "record_id": record_id,
                    "email": record.email,
                    "template_used": email_template,
                    "advantage_element": advantage_element
                }
            else:
                logger.error(f"[TEST EMAIL] Failed to send email to {record.email}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to send email to {record.email}"
                )

        except json.JSONDecodeError as e:
            logger.error(f"[TEST EMAIL] Invalid JSON in full_result_en: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON in full_result_en")
        except ValidationError as e:
            logger.error(f"[TEST EMAIL] Validation error: {e}")
            raise HTTPException(status_code=400, detail=f"Data validation error: {str(e)}")
        except Exception as e:
            logger.error(f"[TEST EMAIL] Email service error: {e}")
            raise HTTPException(status_code=500, detail=f"Email service error: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[TEST EMAIL] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.get("/test/list-records")
async def list_test_records(
        skip: int = 0,
        limit: int = 10,
        only_unpurchased: bool = False,
        db: Session = Depends(get_db)
):
    """列出可用于测试的记录 - 仅用于开发环境"""
    if os.getenv("ENVIRONMENT") == "production":
        raise HTTPException(
            status_code=403,
            detail="This endpoint is not available in production"
        )
    try:
        query = db.query(AstrologyRecord)
        if only_unpurchased:
            query = query.filter(AstrologyRecord.is_purchased == False)
        query = query.filter(AstrologyRecord.full_result_en != None)
        records = query.order_by(AstrologyRecord.created_at.desc()).offset(skip).limit(limit).all()
        result = []
        for record in records:
            result.append({
                "id": record.id,
                "email": record.email,
                "is_purchased": record.is_purchased,
                "shopify_order_id": record.shopify_order_id,
                "created_at": record.created_at.isoformat() if record.created_at else None,
                "has_full_result": bool(record.full_result_en)
            })
        return {
            "total": len(result),
            "skip": skip,
            "limit": limit,
            "records": result
        }

    except Exception as e:
        logger.error(f"[TEST] Error listing records: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/stats")
async def get_admin_stats(
        request: Request,
        db: Session = Depends(get_db),
        _: str = Depends(require_admin_auth)
):
    """获取管理后台统计信息"""
    try:
        product_count = db.query(Product).count()
        translation_count = db.query(DBTranslationPair).count()

        # 获取最近的更新时间
        latest_product = db.query(Product).order_by(Product.id.desc()).first()
        latest_translation = db.query(DBTranslationPair).order_by(
            DBTranslationPair.id.desc()
        ).first()

        return {
            "products": {
                "total": product_count,
                "required": 3,
                "complete": product_count >= 3
            },
            "translations": {
                "total": translation_count
            },
            "last_update": {
                "products": latest_product.id if latest_product else None,
                "translations": latest_translation.id if latest_translation else None
            }
        }
    except Exception as e:
        logger.error(f"Error getting admin stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get statistics")


@router.post("/admin/upload/image")
async def upload_image(
        request: Request,
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
        _: str = Depends(require_admin_auth)
):
    """上传图片文件"""
    try:
        # 验证文件类型
        allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed types: {', '.join(allowed_types)}"
            )

        # 限制文件大小 (5MB)
        max_size = 5 * 1024 * 1024
        contents = await file.read()
        if len(contents) > max_size:
            raise HTTPException(status_code=400, detail="File too large. Maximum size is 5MB")

        # 生成唯一文件名
        import uuid
        from pathlib import Path

        file_extension = Path(file.filename).suffix
        unique_filename = f"{uuid.uuid4()}{file_extension}"

        # 确保上传目录存在
        upload_dir = Path("static/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)

        # 保存文件
        file_path = upload_dir / unique_filename
        with open(file_path, "wb") as f:
            f.write(contents)

        # 返回文件URL
        file_url = f"/static/uploads/{unique_filename}"

        return {
            "url": file_url,
            "filename": unique_filename,
            "size": len(contents)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading image: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload image")


@router.get("/admin/export/translations")
async def export_translations(
        request: Request,
        db: Session = Depends(get_db),
        _: str = Depends(require_admin_auth)
):
    """导出所有翻译为JSON格式"""
    try:
        translations = db.query(DBTranslationPair).all()

        export_data = {
            "version": "1.0.0",
            "export_date": datetime.now().isoformat(),
            "total": len(translations),
            "translations": [
                {
                    "id": t.id,
                    "chinese_text": t.chinese_text,
                    "english_text": t.english_text
                }
                for t in translations
            ]
        }

        return export_data
    except Exception as e:
        logger.error(f"Error exporting translations: {e}")
        raise HTTPException(status_code=500, detail="Failed to export translations")
