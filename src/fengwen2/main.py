import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Header, Query
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.fengwen2.api_routes import router, verify_admin_auth_with_redirect
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


@app.get("/")
async def root():
    """API root endpoint - redirect to documentation"""
    return {
        "message": "Astrology Fortune API",
        "version": "1.0.0",
        "docs": "/docs",
        "admin": "/admin/"
    }


@app.get("/admin/", response_class=HTMLResponse)
async def admin_interface():
    """Serve admin management interface"""
    try:
        with open("static/admin.html", "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content)
    except FileNotFoundError:
        logger.warning("Admin interface HTML not found")
        return HTMLResponse(
            content="""
            <html>
                <head><title>Admin Interface Not Found</title></head>
                <body>
                    <h1>Admin Interface Not Found</h1>
                    <p>The admin interface file is missing. Please check the static files.</p>
                    <p>API documentation: <a href="/docs">/docs</a></p>
                </body>
            </html>
            """
        )


@app.get("/admin/admin-page")
async def get_admin_page(authorization: Optional[str] = Header(None), token: Optional[str] = Query(None)):
    """Serve admin management page from template"""
    from src.fengwen2.api_routes import ADMIN_PASSWORD
    
    # Check authentication from header or URL parameter
    is_authenticated = False
    
    # Check authorization header first
    if authorization:
        try:
            scheme, credentials = authorization.split()
            if scheme.lower() == "bearer" and credentials == ADMIN_PASSWORD:
                is_authenticated = True
        except ValueError:
            pass
    
    # If not authenticated via header, check URL parameter
    if not is_authenticated and token == ADMIN_PASSWORD:
        is_authenticated = True
    
    if not is_authenticated:
        # Return a page that redirects to login with a message
        return HTMLResponse(content=f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>需要登录</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
                .container {{ max-width: 400px; margin: 100px auto; background: white; padding: 30px; border-radius: 8px; text-align: center; }}
                .message {{ color: #666; margin-bottom: 20px; }}
                .button {{ background: #007bff; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; text-decoration: none; display: inline-block; }}
                .button:hover {{ background: #0056b3; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>需要管理员登录</h2>
                <p class="message">您需要先登录才能访问管理页面</p>
                <a href="/admin/?redirected=true" class="button">前往登录</a>
                <p><small>或者 <span id="countdown">3</span> 秒后自动跳转...</small></p>
            </div>
            <script>
                let countdown = 3;
                const countdownElement = document.getElementById('countdown');
                const timer = setInterval(() => {{
                    countdown--;
                    countdownElement.textContent = countdown;
                    if (countdown <= 0) {{
                        clearInterval(timer);
                        window.location.href = '/admin/?redirected=true';
                    }}
                }}, 1000);
            </script>
        </body>
        </html>
        """)
    
    # User is authenticated, serve the admin page
    try:
        with open("templates/admin_page.html", "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content)
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
