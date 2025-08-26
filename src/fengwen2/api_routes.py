from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional
import json
import html
import logging
from urllib.parse import urlparse
import secrets

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('astrology_backend.log')
    ]
)
logger = logging.getLogger(__name__)

from .database import get_db, AstrologyRecord
from .admin_models import Product, TranslationPair as DBTranslationPair
from .models import UserInfoRequest, UserInfoWithVerificationRequest, EmailRequest, VerificationRequest, ProductUpdate, TranslationPairUpdate, TranslationPair as TranslationPairRequest
from .email_service import EmailService
from .shopify_service import ShopifyPaymentService
from .astrology_service import AstrologyService

router = APIRouter()

# Admin authentication
ADMIN_PASSWORD = "admin123"

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

# Initialize services
email_service = EmailService()
shopify_service = ShopifyPaymentService()
astrology_service = AstrologyService()

@router.post("/submit-info")
async def submit_user_info(user_info: UserInfoRequest, db: Session = Depends(get_db)):
    """Submit user info and get preview result"""
    logger.info(f"[API] User info submission started for email: {user_info.email}")
    try:
        record = astrology_service.create_record(
            user_info.email, user_info.name, user_info.birth_date,
            user_info.birth_time, user_info.gender, False, db
        )
        
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
async def send_verification_code(request: EmailRequest):
    """Send email verification code"""
    try:
        verification_code = await email_service.send_verification_email(request.email)
        if verification_code:
            return {"message": "Verification code sent to your email"}
        else:
            raise HTTPException(status_code=500, detail="Failed to send verification code")
    except Exception as e:
        print(f"Error sending verification: {e}")
        raise HTTPException(status_code=500, detail="Failed to send verification code")

@router.post("/verify-email")
async def verify_email(request: VerificationRequest, db: Session = Depends(get_db)):
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
async def shopify_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Shopify payment webhooks"""
    try:
        body = await request.body()
        signature = request.headers.get("X-Shopify-Hmac-Sha256", "")
        
        # Verify webhook (in production)
        # if not shopify_service.verify_webhook(body, signature):
        #     raise HTTPException(status_code=401, detail="Invalid signature")
        
        webhook_data = json.loads(body)
        
        # Extract record ID and update purchase status
        record_id = shopify_service.extract_record_id_from_order(webhook_data)
        if record_id:
            record = db.query(AstrologyRecord).filter(AstrologyRecord.id == record_id).first()
            if record:
                record.is_purchased = True
                record.shopify_order_id = webhook_data.get("id")
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                
                # Send result email
                await email_service.send_astrology_result_email(
                    record.email, record.name, record.full_result_en or "Your astrology reading"
                )
        
        return {"status": "success"}
        
    except Exception as e:
        print(f"Webhook error: {e}")
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
async def add_translation(translation: TranslationPairRequest, db: Session = Depends(get_db), _: str = Depends(verify_admin_auth)):
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
async def update_translation(translation_id: int, translation: TranslationPairUpdate, db: Session = Depends(get_db), _: str = Depends(verify_admin_auth)):
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
async def verify_email_first(request: VerificationRequest):
    """Step 1: Verify email and verification code before form submission"""
    logger.info(f"[API] Email verification started for: {request.email}")
    
    if not email_service.verify_code(request.email, request.code):
        logger.warning(f"[API] Invalid verification code for email: {request.email}")
        raise HTTPException(status_code=400, detail="Invalid verification code")
    
    logger.info(f"[API] Email verification successful for: {request.email}")
    return {"message": "Email verified successfully", "verified": True}

@router.post("/astrology/calculate")
async def calculate_astrology(user_info: UserInfoRequest, db: Session = Depends(get_db)):
    """Step 2: Process complete form submission (email must be pre-verified)"""
    logger.info(f"[API] Astrology calculation started for email: {user_info.email}")
    
    if not email_service.is_email_recently_verified(user_info.email):
        logger.warning(f"[API] Email not verified or expired for: {user_info.email}")
        raise HTTPException(status_code=400, detail="Please verify your email first")
    
    try:
        record = astrology_service.create_record(
            user_info.email, user_info.name, user_info.birth_date,
            user_info.birth_time, user_info.gender, False, db
        )
        
        return await astrology_service.process_complete_astrology(record, db)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in calculate_astrology: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Debug endpoints for testing
@router.get("/debug/verification-code/{email}")
async def get_verification_code_for_testing(email: str, _: str = Depends(verify_admin_auth)):
    """Get verification code for testing purposes (admin only)"""
    code = email_service.get_verification_code_for_testing(email)
    if code:
        logger.info(f"[DEBUG] Retrieved verification code for {email}: {code}")
        return {"email": email, "verification_code": code}
    else:
        logger.warning(f"[DEBUG] No verification code found for {email}")
        raise HTTPException(status_code=404, detail="No verification code found for this email")