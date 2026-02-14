"""Pydantic models for request/response types used by the Givegram API."""

from pydantic import BaseModel, Field, HttpUrl


class LoginRequest(BaseModel):
    """Request body for the /api/login endpoint.

    Carries the Instagram ``sessionid`` cookie so the backend can
    create an authenticated Instaloader session without triggering
    checkpoint/challenge flows.
    """

    session_cookie: str = Field(
        description="Value of the 'sessionid' cookie from an active instagram.com browser session"
    )


class LoginResponse(BaseModel):
    """Response body returned by /api/login.

    Contains the opaque session identifier that the frontend must
    include in all subsequent authenticated requests, along with the
    Instagram username associated with the validated session cookie.
    """

    session_id: str = Field(description="Session ID for subsequent requests")
    username: str = Field(description="Instagram username resolved from the session cookie")


class ValidateSessionRequest(BaseModel):
    """Request body for the /api/validate-session endpoint.

    Used for lightweight session checks on page load to avoid
    hitting the Instagram API unnecessarily.
    """

    session_id: str = Field(description="Session ID to validate")


class ValidateSessionResponse(BaseModel):
    """Response body returned by /api/validate-session.

    A successful response (HTTP 200) confirms the session is alive.
    If the session is invalid or expired, the endpoint returns HTTP 401 instead.
    """

    username: str = Field(description="Instagram username associated with the session")


class FetchCommentsRequest(BaseModel):
    """Request body for the /api/fetch-comments endpoint.

    Contains the Instagram post URL to scrape comments from and
    the session ID of an authenticated Instaloader session.
    """

    url: HttpUrl = Field(description="Public Instagram post URL to fetch comments from")
    session_id: str = Field(description="Session ID obtained from /api/login")


class CommentUserData(BaseModel):
    """Aggregated comment data for a single Instagram user.

    Tracks how many comments a user left on the post,
    used downstream for minimum-comment filtering.
    """

    username: str = Field(description="Instagram username (without @)")
    comment_count: int = Field(ge=1, description="Number of comments this user left on the post")


class FetchCommentsResponse(BaseModel):
    """Response body returned by /api/fetch-comments.

    Provides a deduplicated list of commenters with their comment counts,
    plus a total count for UI display.
    """

    users: list[CommentUserData] = Field(description="List of unique commenters with their comment counts")
    total_comments: int = Field(ge=0, description="Total number of comments fetched from the post")


class PickWinnersRequest(BaseModel):
    """Request body for the /api/pick-winners endpoint.

    The frontend sends the user list (with counts) from a previous
    fetch-comments call along with giveaway settings chosen by the user.
    """

    users: list[CommentUserData] = Field(description="List of commenters with their comment counts")
    num_winners: int = Field(ge=1, le=5, description="How many winners to pick (1-5)")
    min_comments: int = Field(ge=1, le=5, description="Minimum comments a user must have to be eligible (1-5)")


class PickWinnersResponse(BaseModel):
    """Response body returned by /api/pick-winners.

    Contains the list of randomly selected winner usernames.
    """

    winners: list[str] = Field(description="Usernames of the selected winners")
