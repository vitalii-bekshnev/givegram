"""Winner selection logic for Instagram giveaways.

Filters eligible users by minimum comment count and randomly
selects the requested number of winners.
"""

import random

from backend.models import CommentUserData


class InsufficientEligibleUsersError(Exception):
    """Raised when there are fewer eligible users than requested winners.

    This typically means the minimum-comment threshold is too high
    or the post has too few commenters. Lower the threshold or
    fetch a post with more engagement.
    """


def filter_eligible_users(
    users: list[CommentUserData],
    min_comments: int,
) -> list[CommentUserData]:
    """Return only users whose comment count meets the minimum threshold.

    Args:
        users: All commenters with their aggregated comment counts.
        min_comments: The minimum number of comments a user must have
            to be eligible for the giveaway.

    Returns:
        A list of users that meet or exceed ``min_comments``.
    """
    return [user for user in users if user.comment_count >= min_comments]


def pick_winners(
    users: list[CommentUserData],
    num_winners: int,
    min_comments: int,
) -> list[str]:
    """Select random giveaway winners from eligible commenters.

    Filters the user list by ``min_comments``, then randomly samples
    ``num_winners`` usernames from the eligible pool.

    Args:
        users: All commenters with their aggregated comment counts.
        num_winners: How many winners to select (1-5).
        min_comments: Minimum comments a user must have to be eligible.

    Returns:
        A list of winner usernames (without ``@`` prefix).

    Raises:
        InsufficientEligibleUsersError: If the eligible pool is smaller
            than ``num_winners``.
    """
    eligible = filter_eligible_users(users, min_comments)

    if len(eligible) < num_winners:
        raise InsufficientEligibleUsersError(
            f"Only {len(eligible)} user(s) meet the minimum of {min_comments} "
            f"comment(s), but {num_winners} winner(s) requested. "
            f"Try lowering the minimum-comment threshold."
        )

    selected = random.sample(eligible, num_winners)
    return [user.username for user in selected]
