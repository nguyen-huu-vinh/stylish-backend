import os
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, FileResponse

router = APIRouter(tags=["Admin page"])


@router.get("/admin", response_class=HTMLResponse)
def get_admin_page():
    if os.path.exists("admin.html"):
        return FileResponse("admin.html")
    return "<h1>Chưa tìm thấy file admin.html!</h1>"