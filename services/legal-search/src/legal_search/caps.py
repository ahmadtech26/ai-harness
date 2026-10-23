"""Extraction caps: bound how many articles one answer and one user per day can receive."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Caps:
    per_answer: int = 8
    daily: int = 300
    max_results: int = 5


def allowed(requested: int, used_for_answer: int, used_today: int, caps: Caps) -> int:
    """Articles this call may return, after the per-call, per-answer and daily limits."""
    return max(
        0,
        min(requested, caps.max_results, caps.per_answer - used_for_answer, caps.daily - used_today),
    )
