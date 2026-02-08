"""FastAPI application for the Givegram Instagram Giveaway Winner Picker.

Exposes two API endpoints for fetching Instagram post comments and
selecting random giveaway winners, and serves the frontend as static files.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.models import (
    FetchCommentsRequest,
    FetchCommentsResponse,
    PickWinnersRequest,
    PickWinnersResponse,
)
from backend.scraper import (
    InvalidURLError,
    PostNotFoundError,
    PrivatePostError,
    RateLimitError,
    ScraperError,
    fetch_comments,
)
from backend.winner_selector import InsufficientEligibleUsersError, pick_winners

logger = logging.getLogger(__name__)

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(
    title="Givegram",
    description="Instagram Giveaway Winner Picker API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/fetch-comments", response_model=FetchCommentsResponse)
async def api_fetch_comments(request: FetchCommentsRequest) -> FetchCommentsResponse:
    """Scrape comments from a public Instagram post.

    Accepts an Instagram post URL, fetches all comments, and returns
    a deduplicated list of commenters with their comment counts.

    Raises:
        HTTPException 400: If the URL is invalid.
        HTTPException 404: If the post cannot be found.
        HTTPException 403: If the post is private.
        HTTPException 429: If Instagram rate-limits the request.
        HTTPException 502: For any other upstream scraping failure.
    """
    url_str = str(request.url)
    logger.info("Received fetch-comments request for URL: %s", url_str)

    try:
        return fetch_comments(url_str)
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


@app.post("/api/pick-winners", response_model=PickWinnersResponse)
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


@app.get("/")
async def serve_index() -> FileResponse:
    """Serve the frontend single-page application entry point."""
    return FileResponse(_FRONTEND_DIR / "index.html")


# Mount static assets (CSS, JS) after API routes so that
# /api/* paths are matched first and never shadowed.
app.mount("/", StaticFiles(directory=_FRONTEND_DIR), name="frontend")
