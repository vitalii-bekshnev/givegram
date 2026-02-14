"""Tests for backend.models Pydantic request/response types."""

import pytest
from pydantic import ValidationError

from backend.models import (
    CommentUserData,
    FetchCommentsRequest,
    FetchCommentsResponse,
    LoginRequest,
    LoginResponse,
    PickWinnersRequest,
    PickWinnersResponse,
    ValidateSessionRequest,
    ValidateSessionResponse,
)

# ---------------------------------------------------------------------------
# LoginRequest / LoginResponse
# ---------------------------------------------------------------------------


class TestLoginModels:
    """Tests for login-related models."""

    def test_login_request_valid(self) -> None:
        """Construct a valid LoginRequest."""
        req = LoginRequest(session_cookie="abc123")
        assert req.session_cookie == "abc123"

    def test_login_response_valid(self) -> None:
        """Construct a valid LoginResponse."""
        resp = LoginResponse(session_id="sid-1", username="testuser")
        assert resp.session_id == "sid-1"
        assert resp.username == "testuser"


# ---------------------------------------------------------------------------
# ValidateSession
# ---------------------------------------------------------------------------


class TestValidateSessionModels:
    """Tests for session-validation models."""

    def test_validate_request_valid(self) -> None:
        """Construct a valid ValidateSessionRequest."""
        req = ValidateSessionRequest(session_id="sid-1")
        assert req.session_id == "sid-1"

    def test_validate_response_valid(self) -> None:
        """Construct a valid ValidateSessionResponse."""
        resp = ValidateSessionResponse(username="user1")
        assert resp.username == "user1"


# ---------------------------------------------------------------------------
# CommentUserData
# ---------------------------------------------------------------------------


class TestCommentUserData:
    """Tests for CommentUserData field constraints."""

    def test_valid(self) -> None:
        """Construct a valid CommentUserData."""
        user = CommentUserData(username="alice", comment_count=3)
        assert user.username == "alice"
        assert user.comment_count == 3

    def test_comment_count_must_be_at_least_one(self) -> None:
        """Reject comment_count < 1."""
        with pytest.raises(ValidationError, match="comment_count"):
            CommentUserData(username="bad", comment_count=0)


# ---------------------------------------------------------------------------
# FetchCommentsRequest / Response
# ---------------------------------------------------------------------------


class TestFetchCommentsModels:
    """Tests for fetch-comments models."""

    def test_request_valid_url(self) -> None:
        """Accept a valid Instagram URL."""
        req = FetchCommentsRequest(
            url="https://www.instagram.com/p/ABC123/",  # type: ignore[arg-type]
            session_id="sid",
        )
        assert "ABC123" in str(req.url)

    def test_request_invalid_url(self) -> None:
        """Reject a clearly invalid URL."""
        with pytest.raises(ValidationError, match="url"):
            FetchCommentsRequest(url="not-a-url", session_id="sid")  # type: ignore[arg-type]

    def test_response_valid(self) -> None:
        """Construct a valid FetchCommentsResponse."""
        resp = FetchCommentsResponse(
            users=[CommentUserData(username="u1", comment_count=1)],
            total_comments=1,
        )
        assert resp.total_comments == 1
        assert len(resp.users) == 1

    def test_response_total_comments_non_negative(self) -> None:
        """Reject negative total_comments."""
        with pytest.raises(ValidationError, match="total_comments"):
            FetchCommentsResponse(users=[], total_comments=-1)


# ---------------------------------------------------------------------------
# PickWinnersRequest / Response
# ---------------------------------------------------------------------------


class TestPickWinnersModels:
    """Tests for pick-winners models."""

    def test_request_valid_lower_bounds(self) -> None:
        """Accept num_winners=1 and min_comments=1 (lower boundaries)."""
        req = PickWinnersRequest(
            users=[CommentUserData(username="a", comment_count=1)],
            num_winners=1,
            min_comments=1,
        )
        assert req.num_winners == 1
        assert req.min_comments == 1

    def test_request_valid_upper_bounds(self) -> None:
        """Accept num_winners=5 and min_comments=5 (upper boundaries)."""
        req = PickWinnersRequest(
            users=[CommentUserData(username="a", comment_count=1)],
            num_winners=5,
            min_comments=5,
        )
        assert req.num_winners == 5
        assert req.min_comments == 5

    def test_num_winners_too_low(self) -> None:
        """Reject num_winners < 1."""
        with pytest.raises(ValidationError, match="num_winners"):
            PickWinnersRequest(
                users=[],
                num_winners=0,
                min_comments=1,
            )

    def test_num_winners_too_high(self) -> None:
        """Reject num_winners > 5."""
        with pytest.raises(ValidationError, match="num_winners"):
            PickWinnersRequest(
                users=[],
                num_winners=6,
                min_comments=1,
            )

    def test_min_comments_too_low(self) -> None:
        """Reject min_comments < 1."""
        with pytest.raises(ValidationError, match="min_comments"):
            PickWinnersRequest(
                users=[],
                num_winners=1,
                min_comments=0,
            )

    def test_min_comments_too_high(self) -> None:
        """Reject min_comments > 5."""
        with pytest.raises(ValidationError, match="min_comments"):
            PickWinnersRequest(
                users=[],
                num_winners=1,
                min_comments=6,
            )

    def test_response_valid(self) -> None:
        """Construct a valid PickWinnersResponse."""
        resp = PickWinnersResponse(winners=["alice", "bob"])
        assert resp.winners == ["alice", "bob"]
