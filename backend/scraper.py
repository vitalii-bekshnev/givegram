"""Instagram comment scraper using instaloader.

Fetches all comments from a public Instagram post and aggregates
them by username, producing a deduplicated list of commenters
with their respective comment counts.
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass

import instaloader

from backend.models import CommentUserData, FetchCommentsResponse

logger = logging.getLogger(__name__)

# Matches Instagram post URLs and captures the shortcode.
# Supports /p/, /reel/, and /tv/ URL formats.
_INSTAGRAM_POST_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)",
)


class ScraperError(Exception):
    """Base exception for scraper-related errors.

    Subclasses provide more specific context about what went wrong
    during the scraping process.
    """


class InvalidURLError(ScraperError):
    """Raised when the provided URL is not a valid Instagram post URL.

    Provide a URL in the format: https://www.instagram.com/p/<shortcode>/
    """


class PostNotFoundError(ScraperError):
    """Raised when the Instagram post cannot be found.

    The post may have been deleted, or the shortcode is invalid.
    """


class PrivatePostError(ScraperError):
    """Raised when the Instagram post belongs to a private account.

    With authenticated sessions, private posts may be accessible
    if the logged-in user follows the account. Otherwise, only
    public posts can be scraped.
    """


class RateLimitError(ScraperError):
    """Raised when Instagram rate-limits the scraping request.

    Wait a few minutes before retrying, or try again later.
    """


@dataclass(frozen=True, slots=True)
class CommentData:
    """Raw comment data extracted from an Instagram post.

    Attributes:
        username: Instagram handle of the commenter (without @).
        text: Full text content of the comment.
        timestamp: Unix timestamp when the comment was posted.
    """

    username: str
    text: str
    timestamp: float


def extract_shortcode(url: str) -> str:
    """Extract the post shortcode from an Instagram URL.

    Args:
        url: Full Instagram post URL (supports /p/, /reel/, /tv/ paths).

    Returns:
        The alphanumeric shortcode identifying the post.

    Raises:
        InvalidURLError: If the URL does not match any known Instagram post format.
    """
    match = _INSTAGRAM_POST_URL_PATTERN.search(url)
    if not match:
        raise InvalidURLError(
            f"Could not extract shortcode from URL: {url!r}. Expected format: https://www.instagram.com/p/<shortcode>/"
        )
    return match.group(1)


def _fetch_comments_from_post(
    shortcode: str,
    loader: instaloader.Instaloader,
) -> list[CommentData]:
    """Fetch all comments from an Instagram post via instaloader.

    Uses the provided instaloader instance (which may be authenticated)
    to iterate over every comment on the post.

    Args:
        shortcode: The Instagram post shortcode (e.g. 'ABC123').
        loader: A configured Instaloader instance (anonymous or logged-in).

    Returns:
        A list of CommentData objects, one per comment.

    Raises:
        PostNotFoundError: If the post does not exist or has been deleted.
        PrivatePostError: If the post belongs to a private account.
        RateLimitError: If Instagram throttles the request.
        ScraperError: For any other unexpected instaloader failure.
    """
    try:
        post = instaloader.Post.from_shortcode(loader.context, shortcode)
    except instaloader.exceptions.QueryReturnedNotFoundException:
        raise PostNotFoundError(
            f"Post with shortcode {shortcode!r} was not found. It may have been deleted or the URL is incorrect."
        ) from None
    except instaloader.exceptions.LoginRequiredException:
        raise PrivatePostError(
            f"Post with shortcode {shortcode!r} belongs to a private account. Only public posts can be scraped."
        ) from None
    except instaloader.exceptions.ConnectionException as exc:
        error_msg = str(exc).lower()
        if "429" in error_msg or "rate" in error_msg or "too many" in error_msg:
            raise RateLimitError(
                "Instagram is rate-limiting requests. Please wait a few minutes and try again."
            ) from exc
        raise ScraperError(
            f"Failed to fetch post {shortcode!r}: {exc}. Check your network connection and try again."
        ) from exc

    comments: list[CommentData] = []

    try:
        for comment in post.get_comments():
            comments.append(
                CommentData(
                    username=comment.owner.username,
                    text=comment.text,
                    timestamp=comment.created_at_utc.timestamp(),
                )
            )
    except instaloader.exceptions.ConnectionException as exc:
        error_msg = str(exc).lower()
        if "429" in error_msg or "rate" in error_msg or "too many" in error_msg:
            raise RateLimitError(
                "Instagram rate-limited the request while fetching comments. Please wait a few minutes and try again."
            ) from exc
        raise ScraperError(
            f"Error while fetching comments for post {shortcode!r}: {exc}. Some comments may have been missed."
        ) from exc

    logger.info("Fetched %d comments from post %s", len(comments), shortcode)
    return comments


def _aggregate_comments(comments: list[CommentData]) -> list[CommentUserData]:
    """Aggregate raw comments into per-user comment counts.

    Args:
        comments: List of raw comment data from the post.

    Returns:
        A list of CommentUserData, sorted alphabetically by username,
        each containing the total number of comments that user left.
    """
    counts: Counter[str] = Counter(c.username for c in comments)
    return sorted(
        [CommentUserData(username=username, comment_count=count) for username, count in counts.items()],
        key=lambda u: u.username,
    )


def fetch_comments(
    url: str,
    loader: instaloader.Instaloader,
) -> FetchCommentsResponse:
    """Scrape comments from an Instagram post and return aggregated results.

    This is the main entry point used by the API endpoint. It orchestrates
    URL parsing, comment fetching, and aggregation into the response model.

    Args:
        url: Full Instagram post URL.
        loader: A configured Instaloader instance (anonymous or logged-in).

    Returns:
        FetchCommentsResponse with deduplicated user list and total comment count.

    Raises:
        InvalidURLError: If the URL format is not recognised.
        PostNotFoundError: If the post does not exist.
        PrivatePostError: If the post is on a private account.
        RateLimitError: If Instagram throttles the request.
        ScraperError: For any other scraping failure.
    """
    shortcode = extract_shortcode(url)
    logger.info("Scraping comments for post shortcode: %s", shortcode)

    comments = _fetch_comments_from_post(shortcode, loader)
    users = _aggregate_comments(comments)

    response = FetchCommentsResponse(
        users=users,
        total_comments=len(comments),
    )

    logger.info(
        "Completed scraping: %d unique users, %d total comments",
        len(response.users),
        response.total_comments,
    )
    return response
