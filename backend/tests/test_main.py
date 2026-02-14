"""Tests for backend.main FastAPI application."""

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.models import CommentUserData, FetchCommentsResponse
from backend.scraper import (
    InvalidURLError,
    PostNotFoundError,
    PrivatePostError,
    RateLimitError,
    ScraperError,
)
from backend.session_store import LoginFailedError, SessionNotFoundError
from backend.winner_selector import InsufficientEligibleUsersError

BASE_URL = "http://test"


@pytest.fixture()
async def client() -> AsyncIterator[AsyncClient]:
    """Provide an async HTTP client wired to the FastAPI app."""
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url=BASE_URL) as ac:
        yield ac


# ---------------------------------------------------------------------------
# POST /api/login
# ---------------------------------------------------------------------------


class TestApiLogin:
    """Tests for the /api/login endpoint."""

    @patch("backend.main.session_store")
    async def test_success(self, mock_store: MagicMock, client: AsyncClient) -> None:
        """Return session_id and username on successful login."""
        mock_store.login_with_cookie.return_value = ("sid-123", "alice")

        resp = await client.post("/api/login", json={"session_cookie": "cookie_val"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sid-123"
        assert data["username"] == "alice"

    @patch("backend.main.session_store")
    async def test_login_failed(self, mock_store: MagicMock, client: AsyncClient) -> None:
        """Return 401 when the session cookie is invalid."""
        mock_store.login_with_cookie.side_effect = LoginFailedError("bad cookie")

        resp = await client.post("/api/login", json={"session_cookie": "bad"})

        assert resp.status_code == 401
        assert "bad cookie" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/logout
# ---------------------------------------------------------------------------


class TestApiLogout:
    """Tests for the /api/logout endpoint."""

    @patch("backend.main.session_store")
    async def test_success(self, mock_store: MagicMock, client: AsyncClient) -> None:
        """Return success message on logout."""
        resp = await client.post("/api/logout", params={"session_id": "sid-123"})

        assert resp.status_code == 200
        assert resp.json()["detail"] == "Logged out successfully"
        mock_store.remove.assert_called_once_with("sid-123")

    @patch("backend.main.session_store")
    async def test_idempotent(self, mock_store: MagicMock, client: AsyncClient) -> None:
        """Succeed even when the session does not exist (idempotent)."""
        resp = await client.post("/api/logout", params={"session_id": "unknown"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/validate-session
# ---------------------------------------------------------------------------


class TestApiValidateSession:
    """Tests for the /api/validate-session endpoint."""

    @patch("backend.main.session_store")
    async def test_valid(self, mock_store: MagicMock, client: AsyncClient) -> None:
        """Return username for a valid session."""
        mock_store.validate.return_value = "alice"

        resp = await client.post("/api/validate-session", json={"session_id": "sid-123"})

        assert resp.status_code == 200
        assert resp.json()["username"] == "alice"

    @patch("backend.main.session_store")
    async def test_invalid(self, mock_store: MagicMock, client: AsyncClient) -> None:
        """Return 401 for an expired or unknown session."""
        mock_store.validate.side_effect = SessionNotFoundError("not found")

        resp = await client.post("/api/validate-session", json={"session_id": "old"})

        assert resp.status_code == 401
        assert "not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/fetch-comments
# ---------------------------------------------------------------------------


class TestApiFetchComments:
    """Tests for the /api/fetch-comments endpoint."""

    @patch("backend.main.fetch_comments")
    @patch("backend.main.session_store")
    async def test_success(
        self,
        mock_store: MagicMock,
        mock_fetch: MagicMock,
        client: AsyncClient,
    ) -> None:
        """Return comment data on success."""
        mock_store.get_client.return_value = MagicMock()
        mock_fetch.return_value = FetchCommentsResponse(
            users=[CommentUserData(username="alice", comment_count=2)],
            total_comments=2,
        )

        resp = await client.post(
            "/api/fetch-comments",
            json={"url": "https://www.instagram.com/p/ABC123/", "session_id": "sid"},
        )

        assert resp.status_code == 200
        assert resp.json()["total_comments"] == 2

    @patch("backend.main.session_store")
    async def test_session_not_found(self, mock_store: MagicMock, client: AsyncClient) -> None:
        """Return 401 when the session is missing."""
        mock_store.get_client.side_effect = SessionNotFoundError("gone")

        resp = await client.post(
            "/api/fetch-comments",
            json={"url": "https://www.instagram.com/p/ABC123/", "session_id": "bad"},
        )

        assert resp.status_code == 401
        assert "gone" in resp.json()["detail"]

    @patch("backend.main.fetch_comments")
    @patch("backend.main.session_store")
    async def test_invalid_url(
        self,
        mock_store: MagicMock,
        mock_fetch: MagicMock,
        client: AsyncClient,
    ) -> None:
        """Return 400 for an invalid Instagram URL."""
        mock_store.get_client.return_value = MagicMock()
        mock_fetch.side_effect = InvalidURLError("bad url")

        resp = await client.post(
            "/api/fetch-comments",
            json={"url": "https://www.instagram.com/p/ABC123/", "session_id": "sid"},
        )

        assert resp.status_code == 400
        assert "bad url" in resp.json()["detail"]

    @patch("backend.main.fetch_comments")
    @patch("backend.main.session_store")
    async def test_post_not_found(
        self,
        mock_store: MagicMock,
        mock_fetch: MagicMock,
        client: AsyncClient,
    ) -> None:
        """Return 404 when the post does not exist."""
        mock_store.get_client.return_value = MagicMock()
        mock_fetch.side_effect = PostNotFoundError("missing")

        resp = await client.post(
            "/api/fetch-comments",
            json={"url": "https://www.instagram.com/p/ABC123/", "session_id": "sid"},
        )

        assert resp.status_code == 404
        assert "missing" in resp.json()["detail"]

    @patch("backend.main.fetch_comments")
    @patch("backend.main.session_store")
    async def test_private_post(
        self,
        mock_store: MagicMock,
        mock_fetch: MagicMock,
        client: AsyncClient,
    ) -> None:
        """Return 403 when the post is private."""
        mock_store.get_client.return_value = MagicMock()
        mock_fetch.side_effect = PrivatePostError("private")

        resp = await client.post(
            "/api/fetch-comments",
            json={"url": "https://www.instagram.com/p/ABC123/", "session_id": "sid"},
        )

        assert resp.status_code == 403
        assert "private" in resp.json()["detail"]

    @patch("backend.main.fetch_comments")
    @patch("backend.main.session_store")
    async def test_rate_limit(
        self,
        mock_store: MagicMock,
        mock_fetch: MagicMock,
        client: AsyncClient,
    ) -> None:
        """Return 429 when Instagram rate-limits."""
        mock_store.get_client.return_value = MagicMock()
        mock_fetch.side_effect = RateLimitError("throttled")

        resp = await client.post(
            "/api/fetch-comments",
            json={"url": "https://www.instagram.com/p/ABC123/", "session_id": "sid"},
        )

        assert resp.status_code == 429
        assert "throttled" in resp.json()["detail"]

    @patch("backend.main.fetch_comments")
    @patch("backend.main.session_store")
    async def test_scraper_error(
        self,
        mock_store: MagicMock,
        mock_fetch: MagicMock,
        client: AsyncClient,
    ) -> None:
        """Return 502 for a generic upstream scraping failure."""
        mock_store.get_client.return_value = MagicMock()
        mock_fetch.side_effect = ScraperError("boom")

        resp = await client.post(
            "/api/fetch-comments",
            json={"url": "https://www.instagram.com/p/ABC123/", "session_id": "sid"},
        )

        assert resp.status_code == 502
        assert "boom" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/pick-winners
# ---------------------------------------------------------------------------


class TestApiPickWinners:
    """Tests for the /api/pick-winners endpoint."""

    @patch("backend.main.pick_winners")
    async def test_success(self, mock_pick: MagicMock, client: AsyncClient) -> None:
        """Return winner list on success."""
        mock_pick.return_value = ["alice"]

        resp = await client.post(
            "/api/pick-winners",
            json={
                "users": [{"username": "alice", "comment_count": 3}],
                "num_winners": 1,
                "min_comments": 1,
            },
        )

        assert resp.status_code == 200
        assert resp.json()["winners"] == ["alice"]

    @patch("backend.main.pick_winners")
    async def test_insufficient_eligible(self, mock_pick: MagicMock, client: AsyncClient) -> None:
        """Return 422 when not enough eligible users."""
        mock_pick.side_effect = InsufficientEligibleUsersError("not enough")

        resp = await client.post(
            "/api/pick-winners",
            json={
                "users": [{"username": "alice", "comment_count": 1}],
                "num_winners": 5,
                "min_comments": 1,
            },
        )

        assert resp.status_code == 422
        assert "not enough" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET / (frontend serving)
# ---------------------------------------------------------------------------


class TestServeIndex:
    """Tests for the frontend index route."""

    async def test_serve_index(self, client: AsyncClient) -> None:
        """GET / should return the frontend index.html with correct content type."""
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


class TestLifespan:
    """Tests for the application lifespan (background cleanup task)."""

    @patch("backend.main._CLEANUP_INTERVAL_SECONDS", 0)
    @patch("backend.main.session_store")
    async def test_lifespan_starts_and_stops_cleanup(self, mock_store: MagicMock) -> None:
        """Verify the cleanup background task is created, runs, and is cancelled during lifespan."""
        from backend.main import lifespan

        mock_app = MagicMock()

        async with lifespan(mock_app):
            # With interval=0, the background task should fire almost immediately.
            # A small non-zero sleep ensures the event loop schedules the task.
            await asyncio.sleep(0.05)

        # cleanup_expired should have been called at least once.
        mock_store.cleanup_expired.assert_called()
