"""Tests for backend.session_store module."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from instaloader import RateController

from backend.session_store import (
    SESSION_TTL,
    LoginFailedError,
    SessionNotFoundError,
    SessionStore,
    _ConservativeRateController,
    _SessionEntry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_store_with_session(
    *,
    username: str = "testuser",
    created_at: datetime | None = None,
) -> tuple[SessionStore, str]:
    """Create a SessionStore and inject a fake session entry.

    Returns:
        A tuple of (store, session_id).
    """
    store = SessionStore()
    mock_loader = MagicMock()
    entry = _SessionEntry(loader=mock_loader, username=username)
    if created_at is not None:
        entry.created_at = created_at
        entry.last_used = created_at
    session_id = str(uuid.uuid4())
    store._sessions[session_id] = entry
    return store, session_id


# ---------------------------------------------------------------------------
# _ConservativeRateController
# ---------------------------------------------------------------------------


class TestConservativeRateController:
    """Tests for the custom rate controller."""

    def test_count_per_sliding_window_known_types(self) -> None:
        """Return reduced limits for known query types."""
        ctx = MagicMock()
        controller = _ConservativeRateController(ctx)
        assert controller.count_per_sliding_window("graphql") == 120
        assert controller.count_per_sliding_window("other") == 45
        assert controller.count_per_sliding_window("iphone") == 120

    def test_count_per_sliding_window_unknown_type(self) -> None:
        """Return fallback limit for unknown query types."""
        ctx = MagicMock()
        controller = _ConservativeRateController(ctx)
        assert controller.count_per_sliding_window("unknown") == 50

    def test_query_waittime_adds_buffer(self) -> None:
        """Add 50% buffer to the base wait time."""
        ctx = MagicMock()
        controller = _ConservativeRateController(ctx)
        with patch.object(RateController, "query_waittime", return_value=10.0):
            result = controller.query_waittime("graphql", 0.0)
            assert result == 15.0


# ---------------------------------------------------------------------------
# SessionStore.login_with_cookie
# ---------------------------------------------------------------------------


class TestLoginWithCookie:
    """Tests for the login_with_cookie method."""

    @patch("backend.session_store.instaloader.Instaloader")
    def test_success(self, mock_instaloader_cls: MagicMock) -> None:
        """Return (session_id, username) on successful login."""
        mock_loader = MagicMock()
        mock_loader.test_login.return_value = "realuser"
        mock_instaloader_cls.return_value = mock_loader

        store = SessionStore()
        session_id, username = store.login_with_cookie("valid_cookie")

        assert username == "realuser"
        assert session_id  # non-empty UUID
        mock_loader.context.update_cookies.assert_called_once_with({"sessionid": "valid_cookie"})

    @patch("backend.session_store.instaloader.Instaloader")
    def test_login_failed(self, mock_instaloader_cls: MagicMock) -> None:
        """Raise LoginFailedError when test_login returns None."""
        mock_loader = MagicMock()
        mock_loader.test_login.return_value = None
        mock_instaloader_cls.return_value = mock_loader

        store = SessionStore()
        with pytest.raises(LoginFailedError, match="Invalid or expired session cookie"):
            store.login_with_cookie("bad_cookie")


# ---------------------------------------------------------------------------
# SessionStore.get_client
# ---------------------------------------------------------------------------


class TestGetClient:
    """Tests for the get_client method."""

    def test_returns_loader(self) -> None:
        """Return the Instaloader instance for a valid session."""
        store, sid = _create_store_with_session()
        loader = store.get_client(sid)
        assert loader is store._sessions[sid].loader

    def test_unknown_session(self) -> None:
        """Raise SessionNotFoundError for an unknown session ID."""
        store = SessionStore()
        with pytest.raises(SessionNotFoundError, match="Session not found"):
            store.get_client("nonexistent")

    def test_expired_session(self) -> None:
        """Raise SessionNotFoundError when the session has exceeded the TTL."""
        expired_time = datetime.now(UTC) - SESSION_TTL - timedelta(seconds=1)
        store, sid = _create_store_with_session(created_at=expired_time)

        with pytest.raises(SessionNotFoundError, match="expired"):
            store.get_client(sid)

        # Session should have been evicted.
        assert sid not in store._sessions


# ---------------------------------------------------------------------------
# SessionStore.validate
# ---------------------------------------------------------------------------


class TestValidate:
    """Tests for the validate method."""

    def test_returns_username(self) -> None:
        """Return the username for a valid session."""
        store, sid = _create_store_with_session(username="alice")
        assert store.validate(sid) == "alice"

    def test_unknown_session(self) -> None:
        """Raise SessionNotFoundError for an unknown session."""
        store = SessionStore()
        with pytest.raises(SessionNotFoundError):
            store.validate("nope")


# ---------------------------------------------------------------------------
# SessionStore.remove
# ---------------------------------------------------------------------------


class TestRemove:
    """Tests for the remove method."""

    def test_remove_existing(self) -> None:
        """Remove an existing session successfully."""
        store, sid = _create_store_with_session()
        store.remove(sid)
        assert sid not in store._sessions

    def test_remove_unknown_is_noop(self) -> None:
        """Silently ignore removal of a non-existent session."""
        store = SessionStore()
        store.remove("does-not-exist")  # should not raise


# ---------------------------------------------------------------------------
# SessionStore.cleanup_expired
# ---------------------------------------------------------------------------


class TestCleanupExpired:
    """Tests for the cleanup_expired method."""

    def test_removes_only_expired(self) -> None:
        """Remove expired sessions while leaving fresh ones intact."""
        store = SessionStore()

        # Fresh session
        fresh_loader = MagicMock()
        store._sessions["fresh"] = _SessionEntry(loader=fresh_loader, username="fresh_user")

        # Expired session
        old_time = datetime.now(UTC) - SESSION_TTL - timedelta(seconds=10)
        expired_loader = MagicMock()
        store._sessions["old"] = _SessionEntry(
            loader=expired_loader,
            username="old_user",
            created_at=old_time,
            last_used=old_time,
        )

        store.cleanup_expired()

        assert "fresh" in store._sessions
        assert "old" not in store._sessions

    def test_no_expired_sessions(self) -> None:
        """Do nothing when all sessions are fresh."""
        store, sid = _create_store_with_session()
        store.cleanup_expired()
        assert sid in store._sessions
