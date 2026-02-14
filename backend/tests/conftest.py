"""Shared fixtures for Givegram backend tests."""

import pytest

from backend.models import CommentUserData


@pytest.fixture()
def sample_users() -> list[CommentUserData]:
    """Return a representative list of commenters with varying comment counts."""
    return [
        CommentUserData(username="alice", comment_count=3),
        CommentUserData(username="bob", comment_count=1),
        CommentUserData(username="charlie", comment_count=5),
        CommentUserData(username="diana", comment_count=2),
        CommentUserData(username="eve", comment_count=1),
    ]
