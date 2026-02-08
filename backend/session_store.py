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
import instaloader.exceptions

logger = logging.getLogger(__name__)

# Sessions older than this are considered expired and will be removed
# during periodic cleanup.
SESSION_TTL = timedelta(minutes=30)


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class SessionStoreError(Exception):
    """Base exception for session-store-related errors."""


class LoginFailedError(SessionStoreError):
    """Raised when Instagram rejects the provided credentials.

    Double-check the username and password, then try again.
    """


class TwoFactorRequiredError(SessionStoreError):
    """Raised when the Instagram account requires two-factor authentication.

    Two-factor authentication is not supported by this application.
    Disable 2FA on the account or use a different account.
    """


class ChallengeRequiredError(SessionStoreError):
    """Raised when Instagram requires a security challenge (e.g. email/SMS verification).

    Open the Instagram app or website, complete the challenge,
    then try logging in here again.
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
        created_at: UTC timestamp when the session was created.
        last_used: UTC timestamp of the most recent access.
    """

    loader: instaloader.Instaloader
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

    # -- public API ----------------------------------------------------------

    def login(self, username: str, password: str) -> str:
        """Authenticate with Instagram and store the resulting session.

        Args:
            username: Instagram account username.
            password: Instagram account password.

        Returns:
            A UUID4 session ID string for use in subsequent requests.

        Raises:
            LoginFailedError: If the credentials are invalid.
            TwoFactorRequiredError: If the account has 2FA enabled.
            ChallengeRequiredError: If Instagram demands a security challenge.
        """
        loader = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
        )

        try:
            loader.login(username, password)
        except instaloader.exceptions.BadCredentialsException as exc:
            raise LoginFailedError(
                "Invalid username or password. Please check your credentials and try again."
            ) from exc
        except instaloader.exceptions.TwoFactorAuthRequiredException as exc:
            raise TwoFactorRequiredError(
                "This account requires two-factor authentication, which is not supported. "
                "Disable 2FA or use a different account."
            ) from exc
        except instaloader.exceptions.LoginException as exc:
            # Catch the parent LoginException for cases like "Checkpoint required"
            # that aren't raised as a more specific subclass.
            error_msg = str(exc).lower()
            if "checkpoint" in error_msg or "challenge" in error_msg:
                raise ChallengeRequiredError(
                    "Instagram requires a security checkpoint (email/SMS verification). "
                    "Complete the challenge in the Instagram app, then try again."
                ) from exc
            raise LoginFailedError(f"Login failed: {exc}") from exc
        except instaloader.exceptions.ConnectionException as exc:
            error_msg = str(exc).lower()
            if "challenge" in error_msg or "checkpoint" in error_msg:
                raise ChallengeRequiredError(
                    "Instagram requires a security challenge (email/SMS verification). "
                    "Complete the challenge in the Instagram app, then try again."
                ) from exc
            raise LoginFailedError(f"Connection error during login: {exc}. Check your network and try again.") from exc

        session_id = str(uuid.uuid4())
        self._sessions[session_id] = _SessionEntry(loader=loader)

        logger.info(
            "Login successful for user %r, session_id=%s",
            username,
            session_id,
        )
        return session_id

    def get_client(self, session_id: str) -> instaloader.Instaloader:
        """Retrieve an authenticated Instaloader instance by session ID.

        Updates the ``last_used`` timestamp on every access so that
        active sessions are not prematurely expired.

        Args:
            session_id: UUID4 string returned by a previous ``login()`` call.

        Returns:
            The authenticated Instaloader instance associated with the session.

        Raises:
            SessionNotFoundError: If the session ID does not exist or has expired.
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
        return entry.loader

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
