import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta, datetime

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.fengwen2.admin_auth import get_current_admin_user, create_access_token, verify_password, ADMIN_USERNAME, \
    ADMIN_PASSWORD_HASH, ACCESS_TOKEN_EXPIRE_MINUTES
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


@app.get("/")
async def root():
    """API root endpoint - redirect to documentation"""
    return {
        "message": "Astrology Fortune API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    """健康检查端点，包含数据库连接状态"""
    from src.fengwen2.database import check_database_connection

    # 检查数据库连接
    db_status = "ok" if check_database_connection() else "error"

    # 检查各个服务状态
    service_manager = getattr(app.state, 'service_manager', None)

    health_status = {
        "status": "healthy" if db_status == "ok" else "degraded",
        "services": {
            "database": db_status,
            "email": "ok" if service_manager else "unknown",
            "shopify": "ok" if service_manager else "unknown",
            "astrology": "ok" if service_manager else "unknown"
        },
        "database_type": os.getenv("DB_TYPE", "unknown"),
        "timestamp": datetime.utcnow().isoformat()
    }

    if db_status != "ok":
        return JSONResponse(
            status_code=503,
            content=health_status
        )

    return health_status


# Admin routes
@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    """
    管理员登录页面。
    """
    current_user = get_current_admin_user(request)
    if current_user:
        return RedirectResponse(url="/admin", status_code=302)

    login_html_path = os.path.join("static", "login.html")
    if not os.path.exists(login_html_path):
        raise HTTPException(status_code=404, detail="登录页面文件未找到")

    return FileResponse(login_html_path)


@app.post("/admin/login")
async def admin_login(request: Request):
    """管理员登录处理"""
    try:
        data = await request.json()
        username = data.get("username")
        password = data.get("password")

        if not username or not password:
            raise HTTPException(status_code=400, detail="用户名和密码不能为空")

        if username != ADMIN_USERNAME or not verify_password(password, ADMIN_PASSWORD_HASH):
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": username}, expires_delta=access_token_expires
        )

        # 使用 JSONResponse 更符合前后端分离的实践
        response = JSONResponse(content={"message": "Login successful"})
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=int(access_token_expires.total_seconds()),
            samesite="lax",
            path="/"
            # secure=True, # 仅在生产环境(HTTPS)下使用
        )
        return response

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"登录错误: {e}")
        raise HTTPException(status_code=500, detail="服务器内部错误")


@app.get("/admin/logout")
async def admin_logout():
    """管理员登出"""
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie(key="access_token", path="/")
    return response


@app.get("/admin/", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """管理员后台主页面"""
    current_user = get_current_admin_user(request)
    if not current_user:
        return RedirectResponse(url="/admin/login", status_code=302)

    admin_html_path = os.path.join("static", "admin.html")
    if not os.path.exists(admin_html_path):
        raise HTTPException(status_code=404, detail="管理界面文件未找到")

    return FileResponse(admin_html_path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)