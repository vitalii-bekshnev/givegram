"""Pydantic models for request/response types used by the Givegram API."""

from pydantic import BaseModel, Field, HttpUrl


class FetchCommentsRequest(BaseModel):
    """Request body for the /api/fetch-comments endpoint.

    Contains the Instagram post URL to scrape comments from.
    """

    url: HttpUrl = Field(description="Public Instagram post URL to fetch comments from")


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
