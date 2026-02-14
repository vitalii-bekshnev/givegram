"""In-memory session store for authenticated Instaloader instances.

Maps UUID session IDs to logged-in Instaloader instances so that
authenticated scraping requests can reuse existing Instagram sessions
without re-authenticating on every API call.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import instaloader
from instaloader import RateController

logger = logging.getLogger(__name__)

# Sessions older than this are considered expired and will be removed
# during periodic cleanup.
SESSION_TTL = timedelta(minutes=30)


class _ConservativeRateController(RateController):
    """Custom rate controller with more conservative limits for reliability.

    Reduces default Instagram API rate limits to avoid being blocked
    when fetching large numbers of comments.
    """

    def count_per_sliding_window(self, query_type: str) -> int:
        """Reduce default limits by ~40% for reliability."""
        # Default limits: GraphQL=200/11min, Other=75/11min, iPhone=199/30min
        conservative_limits = {
            "graphql": 120,  # reduced from 200
            "other": 45,  # reduced from 75
            "iphone": 120,  # reduced from 199
        }
        return conservative_limits.get(query_type, 50)

    def query_waittime(self, query_type: str, current_time: float, untracked_queries: bool = False) -> float:
        """Add extra buffer time to the calculated wait."""
        base_wait = super().query_waittime(query_type, current_time, untracked_queries)
        return base_wait * 1.5  # 50% extra buffer


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class SessionStoreError(Exception):
    """Base exception for session-store-related errors."""


class LoginFailedError(SessionStoreError):
    """Raised when the provided session cookie is invalid or expired.

    Ensure you are logged into instagram.com, copy a fresh ``sessionid``
    cookie value, and try again.
    """


class SessionNotFoundError(SessionStoreError):
    """Raised when a session ID is not found or has expired.

    Log in again to obtain a new session.
    """


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _SessionEntry:
    """Internal record pairing a logged-in Instaloader instance with timestamps.

    Attributes:
        loader: Authenticated Instaloader instance.
        username: Instagram handle resolved during login.
        created_at: UTC timestamp when the session was created.
        last_used: UTC timestamp of the most recent access.
    """

    loader: instaloader.Instaloader
    username: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_used: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------


class SessionStore:
    """Thread-safe in-memory store for authenticated Instaloader sessions.

    Each successful login creates a new session entry keyed by a UUID4 string.
    Subsequent API calls reference that session ID to retrieve the
    already-authenticated Instaloader instance.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionEntry] = {}

    # -- internal helpers ----------------------------------------------------

    def _get_valid_entry(self, session_id: str) -> _SessionEntry:
        """Look up a session and verify it hasn't expired.

        Updates ``last_used`` on success.

        Args:
            session_id: UUID4 string to look up.

        Returns:
            The live session entry.

        Raises:
            SessionNotFoundError: If the session does not exist or has expired.
        """
        entry = self._sessions.get(session_id)
        if entry is None:
            raise SessionNotFoundError("Session not found or has expired. Please log in again.")

        now = datetime.now(UTC)
        if now - entry.created_at > SESSION_TTL:
            self._sessions.pop(session_id, None)
            logger.info("Session %s expired, removing", session_id)
            raise SessionNotFoundError("Session has expired. Please log in again.")

        entry.last_used = now
        return entry

    # -- public API ----------------------------------------------------------

    def login_with_cookie(self, session_cookie: str) -> tuple[str, str]:
        """Authenticate with Instagram using a browser session cookie.

        Imports the ``sessionid`` cookie from the user's browser session
        to create an authenticated Instaloader instance, bypassing the
        login API (which is blocked by Instagram's checkpoint/challenge system).

        Args:
            session_cookie: The value of the ``sessionid`` cookie from an
                active instagram.com browser session.

        Returns:
            A tuple of ``(session_id, username)`` where *session_id* is a
            UUID4 string for subsequent requests and *username* is the
            Instagram handle associated with the cookie.

        Raises:
            LoginFailedError: If the cookie is invalid, expired, or does
                not resolve to an active Instagram session.
        """
        loader = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            # Rate limiting configurations for reliability
            sleep=True,
            max_connection_attempts=10,
            request_timeout=300.0,
            rate_controller=lambda ctx: _ConservativeRateController(ctx),
        )

        loader.context.update_cookies({"sessionid": session_cookie})
        username = loader.test_login()

        if username is None:
            raise LoginFailedError(
                "Invalid or expired session cookie. "
                "Make sure you are logged into instagram.com, copy a fresh "
                "'sessionid' cookie value, and try again."
            )

        loader.context.username = username

        session_id = str(uuid.uuid4())
        self._sessions[session_id] = _SessionEntry(loader=loader, username=username)

        logger.info(
            "Cookie login successful for user %r, session_id=%s",
            username,
            session_id,
        )
        return session_id, username

    def get_client(self, session_id: str) -> instaloader.Instaloader:
        """Retrieve an authenticated Instaloader instance by session ID.

        Updates the ``last_used`` timestamp on every access so that
        active sessions are not prematurely expired.

        Args:
            session_id: UUID4 string returned by a previous ``login_with_cookie()`` call.

        Returns:
            The authenticated Instaloader instance associated with the session.

        Raises:
            SessionNotFoundError: If the session ID does not exist or has expired.
        """
        return self._get_valid_entry(session_id).loader

    def validate(self, session_id: str) -> str:
        """Check whether a session is still active without hitting Instagram.

        Intended for lightweight session checks on page load so the
        frontend can skip a full re-login when the backend session is
        still alive.  Updates the ``last_used`` timestamp.

        Args:
            session_id: UUID4 string to validate.

        Returns:
            The Instagram username associated with the session.

        Raises:
            SessionNotFoundError: If the session does not exist or has expired.
        """
        return self._get_valid_entry(session_id).username

    def remove(self, session_id: str) -> None:
        """Remove a session, effectively logging the user out.

        Silently ignores unknown session IDs so that logout is idempotent.

        Args:
            session_id: UUID4 string of the session to remove.
        """
        removed = self._sessions.pop(session_id, None)
        if removed is not None:
            logger.info("Session %s removed (logout)", session_id)
        else:
            logger.debug("Attempted to remove unknown session %s", session_id)

    def cleanup_expired(self) -> None:
        """Remove all sessions that have exceeded the TTL.

        Intended to be called periodically (e.g. every few minutes)
        from a background task to prevent unbounded memory growth.
        """
        now = datetime.now(UTC)
        expired_ids = [sid for sid, entry in self._sessions.items() if now - entry.created_at > SESSION_TTL]

        for sid in expired_ids:
            self._sessions.pop(sid, None)

        if expired_ids:
            logger.info(
                "Cleaned up %d expired session(s): %s",
                len(expired_ids),
                expired_ids,
            )


# Module-level singleton used across the application.
session_store = SessionStore()
