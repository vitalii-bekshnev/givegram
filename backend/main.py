"""FastAPI application for the Givegram Instagram Giveaway Winner Picker.

Exposes API endpoints for Instagram login/logout, fetching post comments,
and selecting random giveaway winners. Also serves the frontend as static files.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.models import (
    FetchCommentsRequest,
    FetchCommentsResponse,
    LoginRequest,
    LoginResponse,
    PickWinnersRequest,
    PickWinnersResponse,
    ValidateSessionRequest,
    ValidateSessionResponse,
)
from backend.scraper import (
    InvalidURLError,
    PostNotFoundError,
    PrivatePostError,
    RateLimitError,
    ScraperError,
    fetch_comments,
)
from backend.session_store import (
    LoginFailedError,
    SessionNotFoundError,
    session_store,
)
from backend.winner_selector import InsufficientEligibleUsersError, pick_winners

logger = logging.getLogger(__name__)

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Interval between expired-session cleanup sweeps.
_CLEANUP_INTERVAL_SECONDS = 300  # 5 minutes


async def _periodic_session_cleanup() -> None:
    """Run session_store.cleanup_expired() every _CLEANUP_INTERVAL_SECONDS.

    Intended to be launched as a background task during application lifespan
    so that stale sessions do not accumulate indefinitely.
    """
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
        session_store.cleanup_expired()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application-wide startup and shutdown resources.

    Starts a background task that periodically purges expired sessions.
    The task is cancelled automatically when the application shuts down.
    """
    cleanup_task = asyncio.create_task(_periodic_session_cleanup())
    logger.info("Started periodic session cleanup task (interval=%ds)", _CLEANUP_INTERVAL_SECONDS)
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task
        logger.info("Stopped periodic session cleanup task")


app = FastAPI(
    title="Givegram",
    description="Instagram Giveaway Winner Picker API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


@app.post("/api/login", response_model=LoginResponse)  # type: ignore[untyped-decorator]
async def api_login(request: LoginRequest) -> LoginResponse:
    """Authenticate with Instagram using a session cookie and create a session.

    The returned session_id must be included in subsequent requests
    that require an authenticated Instaloader instance (e.g. fetch-comments).

    Raises:
        HTTPException 401: If the session cookie is invalid or expired.
    """
    logger.info("Login attempt via session cookie")

    try:
        session_id, username = await asyncio.to_thread(session_store.login_with_cookie, request.session_cookie)
    except LoginFailedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return LoginResponse(session_id=session_id, username=username)


@app.post("/api/logout")  # type: ignore[untyped-decorator]
async def api_logout(session_id: str) -> dict[str, str]:
    """Log out by removing the session associated with the given ID.

    This endpoint is idempotent -- calling it with an unknown or already-
    removed session ID will still return a success response.

    Args:
        session_id: The session identifier to invalidate.
    """
    logger.info("Logout request for session %s", session_id)
    session_store.remove(session_id)
    return {"detail": "Logged out successfully"}


@app.post("/api/validate-session", response_model=ValidateSessionResponse)  # type: ignore[untyped-decorator]
async def api_validate_session(request: ValidateSessionRequest) -> ValidateSessionResponse:
    """Check whether a backend session is still alive without hitting Instagram.

    The frontend calls this on page load with a previously stored session_id
    so it can skip a full re-login (which contacts Instagram) when the
    in-memory session is still valid.

    Raises:
        HTTPException 401: If the session does not exist or has expired.
    """
    logger.info("Session validation request for session %s", request.session_id)

    try:
        username = session_store.validate(request.session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return ValidateSessionResponse(username=username)


# ---------------------------------------------------------------------------
# Comment scraping
# ---------------------------------------------------------------------------


@app.post("/api/fetch-comments", response_model=FetchCommentsResponse)  # type: ignore[untyped-decorator]
async def api_fetch_comments(request: FetchCommentsRequest) -> FetchCommentsResponse:
    """Scrape comments from an Instagram post using an authenticated session.

    Accepts an Instagram post URL and a session_id, fetches all comments,
    and returns a deduplicated list of commenters with their comment counts.

    Raises:
        HTTPException 401: If the session is missing or expired.
        HTTPException 400: If the URL is invalid.
        HTTPException 404: If the post cannot be found.
        HTTPException 403: If the post is private.
        HTTPException 429: If Instagram rate-limits the request.
        HTTPException 502: For any other upstream scraping failure.
    """
    url_str = str(request.url)
    logger.info("Received fetch-comments request for URL: %s (session=%s)", url_str, request.session_id)

    try:
        loader = session_store.get_client(request.session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    try:
        return await asyncio.to_thread(fetch_comments, url_str, loader)
    except InvalidURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PostNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PrivatePostError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ScraperError as exc:
        logger.exception("Unexpected scraper error for URL: %s", url_str)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Winner selection
# ---------------------------------------------------------------------------


@app.post("/api/pick-winners", response_model=PickWinnersResponse)  # type: ignore[untyped-decorator]
async def api_pick_winners(request: PickWinnersRequest) -> PickWinnersResponse:
    """Select random giveaway winners from eligible commenters.

    Accepts the commenter list (from a previous fetch-comments call)
    along with giveaway settings, and returns the selected winners.

    Raises:
        HTTPException 422: If there are not enough eligible users
            to fulfil the requested number of winners.
    """
    logger.info(
        "Received pick-winners request: %d users, %d winners, min_comments=%d",
        len(request.users),
        request.num_winners,
        request.min_comments,
    )

    try:
        winners = pick_winners(
            users=request.users,
            num_winners=request.num_winners,
            min_comments=request.min_comments,
        )
    except InsufficientEligibleUsersError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info("Selected winners: %s", winners)
    return PickWinnersResponse(winners=winners)


# ---------------------------------------------------------------------------
# Frontend serving
# ---------------------------------------------------------------------------


@app.get("/")  # type: ignore[untyped-decorator]
async def serve_index() -> FileResponse:
    """Serve the frontend single-page application entry point."""
    return FileResponse(_FRONTEND_DIR / "index.html")


# Mount static assets (CSS, JS) after API routes so that
# /api/* paths are matched first and never shadowed.
app.mount("/", StaticFiles(directory=_FRONTEND_DIR), name="frontend")
