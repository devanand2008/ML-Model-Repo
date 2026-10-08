"""
VisionX AI Analyzer — FastAPI Application Entry Point
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, HTTPException
from security import require_user
import time
from PIL import UnidentifiedImageError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import settings
from database import create_tables, seed_default_models
from api.analyze import router as analyze_router
from api.models import router as models_router
from api.live import router as live_router
from api.reports import router as reports_router
from transit import models as transit_models
from transit.service import initialize as initialize_transit
from api.transit import router as transit_router
from api.mobility import public as mobility_public_router, private as mobility_private_router


# ── Rate Limiter ─────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


# ── Lifespan ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("VisionX AI Analyzer starting …")
    if settings.app_env == "production" and (not settings.auth_enabled or settings.admin_password == "changeme"):
        raise RuntimeError("Production requires AUTH_ENABLED=true and a strong ADMIN_PASSWORD")
    await create_tables()
    await seed_default_models()
    await initialize_transit()
    logger.info("Database ready.")
    cleanup_stop = asyncio.Event()
    cleanup = asyncio.create_task(cleanup_outputs(cleanup_stop))
    try:
        yield
    finally:
        # Finish an in-flight retention transaction before closing its event loop.
        cleanup_stop.set()
        await cleanup
        from database import engine
        await engine.dispose()
        logger.info("VisionX AI Analyzer shutting down.")


# ── App ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="TransitOpt AI / VisionX",
    description="Road traffic and bus crowd camera ML, passenger route intelligence, and transit planning",
    version="2.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_guard(request: Request, call_next):
    origin = request.headers.get("origin")
    same_origin = f"{request.url.scheme}://{request.headers.get('host','')}"
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in settings.cors_origins and origin != same_origin:
        return JSONResponse(status_code=403, content={"error": "Origin not allowed"})
    limit = (500 if request.url.path == "/api/models/upload" else settings.max_file_size_mb) * 1024 * 1024 + 1024 * 1024
    try:
        length = int(request.headers.get("content-length", "0"))
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Invalid Content-Length"})
    if length > limit:
        return JSONResponse(status_code=413, content={"error": "Upload too large"})
    return await call_next(request)

# ── Routes ────────────────────────────────────────────────────────────
app.include_router(analyze_router, prefix="/api/analyze", tags=["Analysis"])
app.include_router(mobility_public_router, prefix="/api")
app.include_router(mobility_private_router, prefix="/api")
from api.rag import router as rag_router
app.include_router(rag_router,prefix='/api')
app.include_router(transit_router, prefix="/api", tags=["TransitOpt AI"])
app.include_router(models_router, prefix="/api",          tags=["Models & History"])
app.include_router(live_router,    prefix="/api/analyze",  tags=["Live Camera"])
app.include_router(reports_router, prefix="/api", tags=["Activity Reports"])


# ── Static file serving for outputs ──────────────────────────────────
@app.get("/api/outputs/{filename}")
async def serve_output(filename: str, user=Depends(require_user)):
    path = (settings.output_dir / filename).resolve()
    if path.parent != settings.output_dir.resolve():
        raise HTTPException(400, "Invalid filename")
    if not path.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)
    return FileResponse(str(path))


# ── Health check ──────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {
        "status":  "ok",
        "version": "2.1.0",
        "env":     settings.app_env,
    }


# ── Error handlers ────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Analysis failed. Check server logs and installed model weights."},
    )


# ── Entry point ───────────────────────────────────────────────────────


async def cleanup_outputs(stop_event: asyncio.Event):
    last_mobility_cleanup = 0.0
    while not stop_event.is_set():
        for folder in (settings.output_dir, settings.upload_dir):
            for path in folder.rglob("*"):
                if path.is_file() and path.name != ".gitkeep" and time.time() - path.stat().st_mtime > settings.output_ttl_seconds:
                    try:
                        path.unlink()
                    except OSError:
                        pass
        if time.monotonic() - last_mobility_cleanup >= 3600:
            from datetime import timedelta
            from sqlalchemy import delete
            from database import AsyncSessionLocal
            from transit.mobility import utc_now
            from transit.models import TransitBusLocation, TransitBusOccupancy, TransitNavigationRequest
            now = utc_now()
            try:
                async with AsyncSessionLocal() as db:
                    await db.execute(delete(TransitBusLocation).where(TransitBusLocation.timestamp < now - timedelta(days=7)))
                    await db.execute(delete(TransitBusOccupancy).where(TransitBusOccupancy.timestamp < now - timedelta(days=30)))
                    await db.execute(delete(TransitNavigationRequest).where(TransitNavigationRequest.timestamp < now - timedelta(days=1)))
                    await db.commit()
            except Exception:
                logger.exception("Could not apply mobility retention; retrying next cycle")
            else:
                last_mobility_cleanup = time.monotonic()
        try:
            await asyncio.wait_for(stop_event.wait(),timeout=60)
        except asyncio.TimeoutError:
            pass

@app.exception_handler(UnidentifiedImageError)
@app.exception_handler(ValueError)
async def invalid_input(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"success": False, "error": "Invalid or corrupt image" if isinstance(exc, UnidentifiedImageError) else str(exc)})

@app.exception_handler(TimeoutError)
async def inference_timeout(request: Request, exc: TimeoutError):
    return JSONResponse(status_code=504, content={"success": False, "error": "Inference timed out; use a smaller image or shorter video."})

@app.exception_handler(FileNotFoundError)
async def missing_model(request: Request, exc: FileNotFoundError):
    return JSONResponse(status_code=503, content={"success": False, "error": "Model unavailable. Install weights in Model Center."})

@app.get("/api/session")
async def session(user=Depends(require_user)):
    from database import AsyncSessionLocal
    from transit.models import TransitAccount
    role = 'admin'
    if user not in {'local',settings.admin_username}:
        async with AsyncSessionLocal() as db:
            account=await db.get(TransitAccount,user)
            role=account.role if account else 'unknown'
    return {"username": user,"role":role}

# Serve the production frontend, while leaving unknown API routes as 404.
from config import BASE_DIR
frontend_dist = BASE_DIR / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")
    @app.get("/{page:path}")
    async def frontend(page: str):
        if page == "api" or page.startswith("api/"):
            raise HTTPException(404, "API route not found")
        public_root = frontend_dist.resolve()
        public_file = (public_root / page).resolve()
        if not public_file.is_relative_to(public_root):
            raise HTTPException(404, "Public file not found")
        if public_file.is_file():
            return FileResponse(public_file)
        return FileResponse(frontend_dist / "index.html", headers={"Cache-Control": "no-store"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
        log_level="info",
    )
