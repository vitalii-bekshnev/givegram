"""Tests for backend.winner_selector module."""

import random

import pytest

from backend.models import CommentUserData
from backend.winner_selector import (
    InsufficientEligibleUsersError,
    filter_eligible_users,
    pick_winners,
)

# ---------------------------------------------------------------------------
# filter_eligible_users
# ---------------------------------------------------------------------------


class TestFilterEligibleUsers:
    """Tests for the filter_eligible_users function."""

    def test_empty_list(self) -> None:
        """Return an empty list when no users are provided."""
        assert filter_eligible_users([], min_comments=1) == []

    def test_all_users_pass(self, sample_users: list[CommentUserData]) -> None:
        """Return all users when every user meets the minimum threshold."""
        result = filter_eligible_users(sample_users, min_comments=1)
        assert len(result) == len(sample_users)

    def test_no_users_pass(self, sample_users: list[CommentUserData]) -> None:
        """Return an empty list when no user meets a very high threshold."""
        result = filter_eligible_users(sample_users, min_comments=100)
        assert result == []

    def test_mixed_threshold(self, sample_users: list[CommentUserData]) -> None:
        """Return only users whose comment count meets or exceeds the threshold."""
        result = filter_eligible_users(sample_users, min_comments=3)
        usernames = {u.username for u in result}
        assert usernames == {"alice", "charlie"}

    def test_exact_threshold(self) -> None:
        """Include a user whose comment count exactly equals the threshold."""
        users = [CommentUserData(username="zara", comment_count=2)]
        result = filter_eligible_users(users, min_comments=2)
        assert len(result) == 1
        assert result[0].username == "zara"


# ---------------------------------------------------------------------------
# pick_winners
# ---------------------------------------------------------------------------


class TestPickWinners:
    """Tests for the pick_winners function."""

    def test_single_winner(self, sample_users: list[CommentUserData]) -> None:
        """Pick exactly one winner from eligible users."""
        random.seed(42)
        winners = pick_winners(sample_users, num_winners=1, min_comments=1)
        assert len(winners) == 1
        assert winners[0] in {u.username for u in sample_users}

    def test_multiple_winners(self, sample_users: list[CommentUserData]) -> None:
        """Pick multiple unique winners."""
        random.seed(42)
        winners = pick_winners(sample_users, num_winners=3, min_comments=1)
        assert len(winners) == 3
        assert len(set(winners)) == 3  # all unique

    def test_exact_pool_size(self, sample_users: list[CommentUserData]) -> None:
        """Succeed when requested winners equals the eligible pool size."""
        eligible = [u for u in sample_users if u.comment_count >= 2]
        winners = pick_winners(sample_users, num_winners=len(eligible), min_comments=2)
        assert set(winners) == {u.username for u in eligible}

    def test_insufficient_eligible_users(self) -> None:
        """Raise InsufficientEligibleUsersError when pool is too small."""
        users = [CommentUserData(username="only_one", comment_count=5)]
        with pytest.raises(InsufficientEligibleUsersError, match="Only 1 user"):
            pick_winners(users, num_winners=3, min_comments=1)

    def test_insufficient_due_to_threshold(self, sample_users: list[CommentUserData]) -> None:
        """Raise when threshold filters out too many users."""
        with pytest.raises(InsufficientEligibleUsersError):
            pick_winners(sample_users, num_winners=3, min_comments=5)

    def test_winners_are_usernames(self, sample_users: list[CommentUserData]) -> None:
        """Returned values are plain username strings, not model objects."""
        random.seed(0)
        winners = pick_winners(sample_users, num_winners=1, min_comments=1)
        assert all(isinstance(w, str) for w in winners)
