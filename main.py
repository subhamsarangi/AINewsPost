"""FastAPI app for ainewspost."""

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

# Windows event loop fix MUST be first, before any async imports
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, Depends, HTTPException, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from jose import JWTError, jwt
from passlib.context import CryptContext

from digest import db, auth

# Config
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(title="AINewsPost")

# Static files
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    os.makedirs("static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Jinja2
jinja_env = Environment(loader=FileSystemLoader("templates"))


def render(template_name: str, **context) -> str:
    """Render template."""
    template = jinja_env.get_template(template_name)
    return template.render(**context)


# ============ ERROR HANDLERS ============


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Return HTML error pages instead of JSON for user-facing errors."""
    if exc.status_code == 401:
        # Only show error message if redirected from a protected route (has referer)
        # First visit to /login won't have referer
        error_msg = None
        referer = request.headers.get("referer")
        if referer and "/login" not in referer:
            error_msg = "Session expired. Please login again."
        return HTMLResponse(
            render("login.html", error=error_msg),
            status_code=401,
        )
    elif exc.status_code == 404:
        return HTMLResponse(
            render("error.html", status=404, message="Page not found"),
            status_code=404,
        )
    elif exc.status_code >= 500:
        return HTMLResponse(
            render(
                "error.html",
                status=exc.status_code,
                message="Server error. Please try again later.",
            ),
            status_code=exc.status_code,
        )
    else:
        return HTMLResponse(
            render("error.html", status=exc.status_code, message=exc.detail),
            status_code=exc.status_code,
        )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions and show error page."""
    return HTMLResponse(
        render(
            "error.html",
            status=500,
            message="An unexpected error occurred. Please try again.",
        ),
        status_code=500,
    )


# ============ AUTH ============


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        user_email: str = payload.get("email")
        if user_id is None or user_email is None:
            return None
        return {"user_id": user_id, "user_email": user_email}
    except JWTError:
        return None


async def get_current_user(request: Request):
    """Extract user from JWT cookie."""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = decode_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return render("login.html")


@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    try:
        with db.connect() as conn:
            user_id = auth.login(conn, email, password)
        token = create_access_token(
            data={"sub": user_id, "email": email},
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            "access_token",
            token,
            httponly=True,
            secure=os.getenv("ENVIRONMENT") == "production",
            samesite="Lax",
        )
        return response
    except auth.AuthError as e:
        return HTMLResponse(render("login.html", error=str(e)), status_code=401)
    except Exception as e:
        return HTMLResponse(render("login.html", error=str(e)), status_code=500)


@app.get("/digests", response_class=HTMLResponse)
async def digests_page(
    request: Request,
    current_user: dict = Depends(get_current_user),
    date: Optional[str] = None,
):
    """List of daily digests or show specific digest."""
    from digest.config import load_sources
    from datetime import date as date_type
    import json

    try:
        with db.connect() as conn:
            digests = db.list_digests(conn, limit=60)

            # Get digest for requested date or today
            if date:
                digest_obj_date = datetime.fromisoformat(date).date()
            else:
                digest_obj_date = date_type.today()

            today_digest = db.get_digest(conn, digest_obj_date)
            today_items = []
            if today_digest:
                digest_item_rows = db.digest_items(conn, today_digest["id"])
                for row in digest_item_rows:
                    item = db.get_item(conn, row["id"])
                    if item:
                        today_items.append(item)

        # Convert to JSON-serializable dicts
        digests_list = []
        for d in digests:
            item = dict(d)
            if "date" in item and hasattr(item["date"], "isoformat"):
                item["date"] = item["date"].isoformat()
            digests_list.append(item)

        sources = load_sources()
        sources_by_category = {}
        for src in sources:
            cat = src.get("category", "other")
            if cat not in sources_by_category:
                sources_by_category[cat] = []
            sources_by_category[cat].append(src)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return HTMLResponse(
        render(
            "digests.html",
            user_email=current_user["user_email"],
            digests=json.dumps(digests_list),
            today_items=today_items,
            today_digest=today_digest,
            selected_date=date or digest_obj_date.isoformat(),
            sources_by_category=sources_by_category,
        )
    )


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response


# ============ PAGES ============


@app.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    current_user: dict = Depends(get_current_user),
    page: int = 1,
    search: str = "",
    date_filter: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
    starred: bool = False,
):
    """Home page with item list."""
    from digest import search as search_module
    from digest.config import load_sources

    # Parse filters
    hours = {"24h": 24, "7d": 7 * 24, "30d": 30 * 24}.get(date_filter)
    since = datetime.now(timezone.utc) - timedelta(hours=hours) if hours else None

    # Get items
    try:
        with db.connect() as conn:
            items = search_module.search(
                conn,
                search or None,
                source_id=source,
                category=category,
                since=since,
                starred=starred or None,
                sort="date",
                limit=21,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    has_more = len(items) > 20
    items = items[:20]

    # Load sources for sidebar, group by category
    try:
        sources = load_sources()
        sources_by_category = {}
        for src in sources:
            cat = src.get("category", "other")
            if cat not in sources_by_category:
                sources_by_category[cat] = []
            sources_by_category[cat].append(src)
        # Find source name if filtering by source
        source_name = None
        if source:
            for src in sources:
                if src.get("id") == source:
                    source_name = src.get("name")
                    break
    except Exception:
        sources_by_category = {}
        source_name = None

    return HTMLResponse(
        render(
            "index.html",
            user_email=current_user["user_email"],
            items=items,
            page=page,
            has_more=has_more,
            search=search,
            date_filter=date_filter,
            category=category,
            source=source,
            source_name=source_name,
            starred=starred,
            sources_by_category=sources_by_category,
        )
    )


@app.get("/item/{item_slug}", response_class=HTMLResponse)
async def item_detail(
    request: Request,
    item_slug: str,
    current_user: dict = Depends(get_current_user),
):
    """Item detail page."""
    from digest.config import load_sources

    try:
        with db.connect() as conn:
            item = db.get_item_by_slug(conn, item_slug)
            if not item:
                raise HTTPException(status_code=404, detail="Item not found")

            # Similar items
            similar = db.similar_items(conn, item["id"], 5)

            # Related items (cluster)
            others = []
            if item.get("cluster_id"):
                others = [
                    m
                    for m in db.cluster_members(conn, item["cluster_id"])
                    if m["id"] != item["id"]
                ]
        sources = load_sources()
        sources_by_category = {}
        for src in sources:
            cat = src.get("category", "other")
            if cat not in sources_by_category:
                sources_by_category[cat] = []
            sources_by_category[cat].append(src)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return HTMLResponse(
        render(
            "item_detail.html",
            user_email=current_user["user_email"],
            item=item,
            similar=similar,
            others=others,
            sources_by_category=sources_by_category,
        )
    )


@app.post("/api/digest/{digest_date}/rebuild-pdf")
async def rebuild_digest_pdf(
    digest_date: str,
    current_user: dict = Depends(get_current_user),
):
    """Rebuild PDF for a digest."""
    try:
        from digest import pdf, r2

        digest_obj_date = datetime.fromisoformat(digest_date).date()

        with db.connect() as conn:
            digest = db.get_digest(conn, digest_obj_date)
            if not digest:
                return {"status": "error", "message": "Digest not found"}

            # Get items
            digest_item_rows = db.digest_items(conn, digest["id"])
            items = []
            for row in digest_item_rows:
                item = db.get_item(conn, row["id"])
                if item:
                    items.append(item)

            # Generate PDF
            pdf_bytes = await pdf.render_bytes(digest_obj_date, items)
            pdf_path = r2.upload(pdf_bytes, f"digests/{digest_obj_date}.pdf")

            # Update digest
            conn.execute(
                "UPDATE digests SET pdf_path = %s WHERE id = %s",
                (pdf_path, digest["id"]),
            )
            conn.commit()

        return {"status": "ok", "pdf_path": pdf_path}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def star_item(
    item_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Star/unstar item."""
    try:
        with db.connect() as conn:
            item = db.get_item(conn, int(item_id))
            if not item:
                raise HTTPException(status_code=404, detail="Item not found")

            new_state = not item.get("starred", False)
            db.set_starred(conn, int(item_id), new_state)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"starred": new_state}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    import sys

    # Windows + asyncio subprocess fix for Playwright
    if sys.platform == "win32":
        import asyncio

        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=os.getenv("ENVIRONMENT") != "production",
    )
