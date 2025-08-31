import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.fengwen2.api_routes import router
from src.fengwen2.cache_config import init_cache
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

# Mount static files for admin interface
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
else:
    logger.warning("Static directory not found")


@app.get("/", response_class=HTMLResponse)
async def root():
    """redirect to user interface"""
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content)
    except FileNotFoundError:
        logger.warning("User interface HTML not found")
        return HTMLResponse(
            content="""
            <html>
                <head><title>Astrology Fortune</title></head>
                <body>
                    <h1>Welcome to Astrology Fortune API</h1>
                    <p>User interface not found. Please check the static files.</p>
                    <p>API documentation: <a href="/docs">/docs</a></p>
                </body>
            </html>
            """
        )


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
