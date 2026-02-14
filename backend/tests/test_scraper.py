"""Tests for backend.scraper module."""

from unittest.mock import MagicMock, patch

import instaloader.exceptions
import pytest
from instaloader import NodeIterator

from backend.models import CommentUserData
from backend.scraper import (
    CommentData,
    InvalidURLError,
    PostNotFoundError,
    PrivatePostError,
    RateLimitError,
    ScraperError,
    _aggregate_comments,
    _fetch_comments_from_post,
    _is_rate_limit_error,
    _is_transient_error,
    extract_shortcode,
    fetch_comments,
)

# ---------------------------------------------------------------------------
# extract_shortcode
# ---------------------------------------------------------------------------


class TestExtractShortcode:
    """Tests for the extract_shortcode helper."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://www.instagram.com/p/ABC123/", "ABC123"),
            ("https://instagram.com/p/ABC123", "ABC123"),
            ("https://www.instagram.com/reel/XYZ789/", "XYZ789"),
            ("https://www.instagram.com/tv/TV_code-1/", "TV_code-1"),
            ("http://www.instagram.com/p/short/", "short"),
        ],
    )
    def test_valid_urls(self, url: str, expected: str) -> None:
        """Extract the shortcode from various valid Instagram URL formats."""
        assert extract_shortcode(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.google.com",
            "not-a-url",
            "https://www.instagram.com/stories/user/",
            "",
        ],
    )
    def test_invalid_urls(self, url: str) -> None:
        """Raise InvalidURLError for non-post Instagram URLs and junk input."""
        with pytest.raises(InvalidURLError, match="Could not extract shortcode"):
            extract_shortcode(url)


# ---------------------------------------------------------------------------
# _is_transient_error / _is_rate_limit_error
# ---------------------------------------------------------------------------


class TestErrorClassifiers:
    """Tests for the transient and rate-limit error classifiers."""

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("something went wrong", True),
            ("Please try again later", True),
            ("temporarily unavailable", True),
            ("Internal server error occurred", True),
            ("Post not found", False),
            ("Login required", False),
        ],
    )
    def test_is_transient_error(self, message: str, expected: bool) -> None:
        """Classify ConnectionExceptions as transient or not."""
        exc = instaloader.exceptions.ConnectionException(message)
        assert _is_transient_error(exc) is expected

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("429 Too Many Requests", True),
            ("rate limit exceeded", True),
            ("too many requests", True),
            ("something went wrong", False),
            ("Post not found", False),
        ],
    )
    def test_is_rate_limit_error(self, message: str, expected: bool) -> None:
        """Classify ConnectionExceptions as rate-limit or not."""
        exc = instaloader.exceptions.ConnectionException(message)
        assert _is_rate_limit_error(exc) is expected


# ---------------------------------------------------------------------------
# _aggregate_comments
# ---------------------------------------------------------------------------


class TestAggregateComments:
    """Tests for the _aggregate_comments helper."""

    def test_empty(self) -> None:
        """Return an empty list for no comments."""
        assert _aggregate_comments([]) == []

    def test_single_user_multiple_comments(self) -> None:
        """Aggregate multiple comments from the same user."""
        comments = [
            CommentData(username="alice", text="first", timestamp=1.0),
            CommentData(username="alice", text="second", timestamp=2.0),
        ]
        result = _aggregate_comments(comments)
        assert len(result) == 1
        assert result[0] == CommentUserData(username="alice", comment_count=2)

    def test_sorted_by_username(self) -> None:
        """Return results sorted alphabetically by username."""
        comments = [
            CommentData(username="zara", text="hi", timestamp=1.0),
            CommentData(username="alice", text="hello", timestamp=2.0),
        ]
        result = _aggregate_comments(comments)
        assert [u.username for u in result] == ["alice", "zara"]


# ---------------------------------------------------------------------------
# _fetch_comments_from_post
# ---------------------------------------------------------------------------


def _make_mock_comment(username: str, text: str, timestamp: float) -> MagicMock:
    """Create a mock instaloader comment object."""
    comment = MagicMock()
    comment.owner.username = username
    comment.text = text
    mock_dt = MagicMock()
    mock_dt.timestamp.return_value = timestamp
    comment.created_at_utc = mock_dt
    return comment


class TestFetchCommentsFromPost:
    """Tests for _fetch_comments_from_post with mocked instaloader."""

    @patch("backend.scraper.time.sleep")
    @patch("backend.scraper.instaloader.Post.from_shortcode")
    def test_success(self, mock_from_shortcode: MagicMock, mock_sleep: MagicMock) -> None:
        """Return comment data on a successful fetch."""
        mock_post = MagicMock()
        mock_post.get_comments.return_value = [
            _make_mock_comment("alice", "nice!", 100.0),
            _make_mock_comment("bob", "great!", 200.0),
        ]
        mock_from_shortcode.return_value = mock_post

        loader = MagicMock()
        comments = _fetch_comments_from_post("ABC123", loader)

        assert len(comments) == 2
        assert comments[0].username == "alice"
        assert comments[1].username == "bob"

    @patch("backend.scraper.instaloader.Post.from_shortcode")
    def test_post_not_found(self, mock_from_shortcode: MagicMock) -> None:
        """Raise PostNotFoundError for QueryReturnedNotFoundException."""
        mock_from_shortcode.side_effect = instaloader.exceptions.QueryReturnedNotFoundException("404")

        with pytest.raises(PostNotFoundError, match="was not found"):
            _fetch_comments_from_post("MISSING", MagicMock())

    @patch("backend.scraper.instaloader.Post.from_shortcode")
    def test_private_post(self, mock_from_shortcode: MagicMock) -> None:
        """Raise PrivatePostError for LoginRequiredException."""
        mock_from_shortcode.side_effect = instaloader.exceptions.LoginRequiredException("private")

        with pytest.raises(PrivatePostError, match="private account"):
            _fetch_comments_from_post("PRIVATE", MagicMock())

    @patch("backend.scraper.instaloader.Post.from_shortcode")
    def test_rate_limit_on_post_load(self, mock_from_shortcode: MagicMock) -> None:
        """Raise RateLimitError when loading the post hits a rate limit."""
        mock_from_shortcode.side_effect = instaloader.exceptions.ConnectionException("429 Too Many Requests")

        with pytest.raises(RateLimitError, match="rate-limiting"):
            _fetch_comments_from_post("RATELIMITED", MagicMock())

    @patch("backend.scraper.instaloader.Post.from_shortcode")
    def test_generic_connection_error_on_post_load(self, mock_from_shortcode: MagicMock) -> None:
        """Raise ScraperError for a non-rate-limit ConnectionException during post load."""
        mock_from_shortcode.side_effect = instaloader.exceptions.ConnectionException("network down")

        with pytest.raises(ScraperError, match="Failed to fetch post"):
            _fetch_comments_from_post("BROKEN", MagicMock())

    @patch("backend.scraper.time.sleep")
    @patch("backend.scraper.instaloader.Post.from_shortcode")
    def test_rate_limit_during_comment_iteration(
        self,
        mock_from_shortcode: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Raise RateLimitError when iterating comments hits a rate limit."""
        mock_post = MagicMock()
        mock_post.get_comments.side_effect = instaloader.exceptions.ConnectionException("429")
        mock_from_shortcode.return_value = mock_post

        with pytest.raises(RateLimitError, match="rate-limited"):
            _fetch_comments_from_post("RL", MagicMock())

    @patch("backend.scraper.time.sleep")
    @patch("backend.scraper.instaloader.Post.from_shortcode")
    def test_transient_error_retries_then_fails(
        self,
        mock_from_shortcode: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Exhaust retries on repeated transient errors and raise ScraperError."""
        mock_post = MagicMock()
        mock_post.get_comments.side_effect = instaloader.exceptions.ConnectionException("something went wrong")
        mock_from_shortcode.return_value = mock_post

        with pytest.raises(ScraperError, match="Error while fetching comments"):
            _fetch_comments_from_post("TRANSIENT", MagicMock())

        # With _MAX_RETRIES=3, exactly 2 backoff sleeps occur (after attempt 1 and 2).
        assert mock_sleep.call_count == 2

    @patch("backend.scraper.time.sleep")
    @patch("backend.scraper.instaloader.Post.from_shortcode")
    def test_transient_error_recovers(
        self,
        mock_from_shortcode: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Recover after a transient error on the first attempt."""
        mock_post = MagicMock()
        comments = [_make_mock_comment("u1", "hi", 1.0)]

        # First call raises transient error, second succeeds.
        mock_post.get_comments.side_effect = [
            instaloader.exceptions.ConnectionException("something went wrong"),
            comments,
        ]
        mock_from_shortcode.return_value = mock_post

        result = _fetch_comments_from_post("RECOVER", MagicMock())
        assert len(result) == 1
        assert result[0].username == "u1"

    @patch("backend.scraper.time.sleep")
    @patch("backend.scraper.instaloader.Post.from_shortcode")
    def test_non_transient_error_does_not_retry(
        self,
        mock_from_shortcode: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Raise immediately for a non-transient, non-rate-limit ConnectionException."""
        mock_post = MagicMock()
        mock_post.get_comments.side_effect = instaloader.exceptions.ConnectionException("some unique error")
        mock_from_shortcode.return_value = mock_post

        with pytest.raises(ScraperError, match="Error while fetching comments"):
            _fetch_comments_from_post("NONTRANSIENT", MagicMock())

        # Non-transient errors should not trigger backoff sleeps.
        mock_sleep.assert_not_called()

    @patch("backend.scraper.time.sleep")
    @patch("backend.scraper.instaloader.Post.from_shortcode")
    def test_pagination_delay(self, mock_from_shortcode: MagicMock, mock_sleep: MagicMock) -> None:
        """Apply pagination delay when fetching more than 12 comments."""
        mock_post = MagicMock()
        # 13 comments to trigger one pagination delay at index 12.
        mock_post.get_comments.return_value = [_make_mock_comment(f"user{i}", "text", float(i)) for i in range(13)]
        mock_from_shortcode.return_value = mock_post

        result = _fetch_comments_from_post("PAGINATED", MagicMock())
        assert len(result) == 13
        # At least one pagination sleep should have been called.
        assert mock_sleep.called

    @patch("backend.scraper.time.sleep")
    @patch("backend.scraper.instaloader.Post.from_shortcode")
    def test_progressive_backoff_for_large_comment_sections(
        self,
        mock_from_shortcode: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Apply progressive backoff when comment count exceeds the threshold."""
        mock_post = MagicMock()
        # 61 comments: triggers progressive backoff at comment indices 60 (> 50 threshold).
        mock_post.get_comments.return_value = [_make_mock_comment(f"user{i}", "text", float(i)) for i in range(61)]
        mock_from_shortcode.return_value = mock_post

        result = _fetch_comments_from_post("BIGPOST", MagicMock())
        assert len(result) == 61

        # Check that sleep was called with a value > base delay (progressive backoff).
        sleep_values = [call.args[0] for call in mock_sleep.call_args_list]
        base_delay = 1.0  # _PAGINATION_DELAY_SECONDS
        assert any(v > base_delay for v in sleep_values)

    @patch("backend.scraper.time.sleep")
    @patch("backend.scraper.instaloader.Post.from_shortcode")
    def test_graphql_page_length_restored_after_success(
        self,
        mock_from_shortcode: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Verify NodeIterator._graphql_page_length is restored after a successful fetch."""
        original_value = NodeIterator._graphql_page_length

        mock_post = MagicMock()
        mock_post.get_comments.return_value = [_make_mock_comment("u1", "hi", 1.0)]
        mock_from_shortcode.return_value = mock_post

        _fetch_comments_from_post("OK", MagicMock())

        assert NodeIterator._graphql_page_length == original_value

    @patch("backend.scraper.time.sleep")
    @patch("backend.scraper.instaloader.Post.from_shortcode")
    def test_graphql_page_length_restored_after_error(
        self,
        mock_from_shortcode: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Verify NodeIterator._graphql_page_length is restored even after an error."""
        original_value = NodeIterator._graphql_page_length

        mock_post = MagicMock()
        mock_post.get_comments.side_effect = instaloader.exceptions.ConnectionException("some unique error")
        mock_from_shortcode.return_value = mock_post

        with pytest.raises(ScraperError):
            _fetch_comments_from_post("FAIL", MagicMock())

        assert NodeIterator._graphql_page_length == original_value


# ---------------------------------------------------------------------------
# fetch_comments (integration of extract + fetch + aggregate)
# ---------------------------------------------------------------------------


class TestFetchComments:
    """Tests for the top-level fetch_comments orchestrator."""

    @patch("backend.scraper._fetch_comments_from_post")
    def test_success(self, mock_fetch: MagicMock) -> None:
        """Return aggregated response for a valid URL."""
        mock_fetch.return_value = [
            CommentData(username="alice", text="one", timestamp=1.0),
            CommentData(username="alice", text="two", timestamp=2.0),
            CommentData(username="bob", text="three", timestamp=3.0),
        ]

        resp = fetch_comments("https://www.instagram.com/p/TEST123/", MagicMock())

        assert resp.total_comments == 3
        assert len(resp.users) == 2
        usernames = {u.username for u in resp.users}
        assert usernames == {"alice", "bob"}

    def test_invalid_url_raises(self) -> None:
        """Raise InvalidURLError for a bad URL before attempting to fetch."""
        with pytest.raises(InvalidURLError):
            fetch_comments("https://notinstagram.com/oops", MagicMock())
