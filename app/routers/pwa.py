"""PWA：manifest、Service Worker、離線頁。"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.config import get_settings
from app.templating import brand, templates

router = APIRouter()
SW_FILE = Path(__file__).resolve().parent.parent / "static" / "sw.js"
# Cloud Run 每次部署的版本名稱，用來讓 Service Worker 換新快取
VERSION = os.environ.get("K_REVISION") or "dev"


@router.get("/manifest.webmanifest")
async def manifest():
    s = get_settings()
    icons = [
        {"src": brand("icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": brand("icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": brand("maskable-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
        {"src": brand("maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ]
    data = {
        "name": f"{s.app_name}｜{s.app_tagline}",
        "short_name": s.app_name,
        "description": "寫下一個字、說出心中所問，由解題老師親自為你解字。",
        "lang": "zh-Hant-TW",
        "start_url": "/?source=pwa",
        "scope": "/",
        "display": "standalone",
        "background_color": "#262c2e",
        "theme_color": "#262c2e",
        "icons": icons,
        "shortcuts": [
            {"name": "問字", "url": "/ask", "icons": [{"src": brand("icon-192.png"), "sizes": "192x192"}]},
            {"name": "我的問字", "url": "/me", "icons": [{"src": brand("icon-192.png"), "sizes": "192x192"}]},
        ],
    }
    return JSONResponse(data, media_type="application/manifest+json")


@router.get("/sw.js")
async def service_worker():
    js = SW_FILE.read_text(encoding="utf-8").replace("__VERSION__", VERSION)
    return Response(js, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@router.get("/offline")
async def offline(request: Request):
    return templates.TemplateResponse(request, "offline.html", {})
