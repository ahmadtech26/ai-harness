"""Extraction caps: bound how many articles one answer and one user per day can receive."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Caps:
    per_answer: int = 8
    daily: int = 300
    max_results: int = 5


@dataclass(frozen=True)
class Grant:
    count: int
    bound: str | None  # 'per_answer' or 'daily' when count is 0 because that cap is spent; None otherwise


def grant(requested: int, used_for_answer: int, used_today: int, caps: Caps) -> Grant:
    """Articles this call may return, after the per-call, per-answer and daily limits, and which cap refused it."""
    count = max(0, min(requested, caps.max_results, caps.per_answer - used_for_answer, caps.daily - used_today))
    if count > 0 or requested <= 0:
        return Grant(count, None)
    # The daily cap wins when both are spent: a new question does not help then.
    return Grant(0, 'daily' if caps.daily - used_today <= 0 else 'per_answer')


def allowed(requested: int, used_for_answer: int, used_today: int, caps: Caps) -> int:
    """Articles this call may return, after the per-call, per-answer and daily limits."""
    return grant(requested, used_for_answer, used_today, caps).count


def left_for_answer(used_for_answer: int, used_today: int, caps: Caps) -> int:
    """Texts this answer may still receive: the smaller remainder of the per-answer and daily caps, never below 0."""
    return max(0, min(caps.per_answer - used_for_answer, caps.daily - used_today))
