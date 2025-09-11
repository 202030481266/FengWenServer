import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Header, Query, Form, Request
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.fengwen2.admin_auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES, ADMIN_PASSWORD_HASH,
    ADMIN_USERNAME, create_access_token, get_current_admin_user, verify_password
)
from src.fengwen2.api_routes import router
from src.fengwen2.cache_config import init_cache
from src.fengwen2.database import create_tables
from src.fengwen2.service_manager import get_service_manager

# app logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

# load env variables
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up the application...")
    service_manager = get_service_manager()
    try:
        # create the tables
        logger.info("Creating database tables...")
        create_tables()
        logger.info("Database tables created successfully")

        await init_cache()
        await service_manager.startup()
        logger.info("All services started successfully")
    except Exception as e:
        logger.error(f"Error during startup: {e}")
        raise  # stop the service

    app.state.service_manager = service_manager

    yield  # start the app service

    logger.info("Shutting down the application...")
    try:
        await service_manager.shutdown()
        logger.info("All services shut down successfully")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


app = FastAPI(
    title="Astrology Fortune API",
    version="1.0.0",
    description="Astrology service backend",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, prefix="/api")

# Mount static files directory
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
else:
    logger.warning("Static directory not found")

# Setup templates
templates = Jinja2Templates(directory="templates")


@app.get("/")
async def root():
    """API root endpoint - redirect to documentation"""
    return {
        "message": "Astrology Fortune API",
        "version": "1.0.0",
        "docs": "/docs",
        "admin": "/admin/"
    }


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    """Serve the admin login page"""
    return templates.TemplateResponse("admin_login.html", {"request": request})


@app.post("/admin/login")
async def login_for_access_token(
        request: Request,
        username: str = Form(...),
        password: str = Form(...)
):
    """Handle admin login and set session cookie"""
    if username != ADMIN_USERNAME or not verify_password(password, ADMIN_PASSWORD_HASH):
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "无效的用户名或密码"},
            status_code=401
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": username}, expires_delta=access_token_expires
    )

    response = RedirectResponse(url="/admin/admin-page", status_code=302)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=int(access_token_expires.total_seconds()),
        samesite="Lax"
    )
    return response


@app.get("/admin/logout")
async def admin_logout():
    """Handle admin logout and clear session cookie"""
    response = RedirectResponse(url="/admin/login")
    response.delete_cookie(key="access_token")
    return response


@app.get("/admin/", response_class=HTMLResponse)
async def admin_interface(admin: str = Depends(get_current_admin_user)):
    """Redirect to admin page if logged in, otherwise to login page"""
    if admin:
        return RedirectResponse(url="/admin/admin-page")
    return RedirectResponse(url="/admin/login")


@app.get("/admin/admin-page", response_class=HTMLResponse)
async def get_admin_page(request: Request, admin: str = Depends(get_current_admin_user)):
    """Serve admin management page from template, protected by authentication"""
    if not admin:
        return RedirectResponse(url="/admin/login")

    try:
        return templates.TemplateResponse("admin_page.html", {"request": request})
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Admin template not found")


@app.get("/health")
async def health():
    health_status = {
        "status": "healthy",
        "services": {
            "email": "ok",
            "shopify": "ok",
            "astrology": "ok"
        }
    }
    return health_status


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
