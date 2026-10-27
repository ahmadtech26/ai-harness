"""Sweep enforcement (spec C.2) around every retrieval in tools.py.

    decide()  before anything is served: the user's open flag, then the detector over the user's events after
              their watermark plus this call. A proven flag, or a proven verdict, suspends: nothing is served.
              A suspected flag, or a suspected verdict, throttles: the daily cap becomes throttle_daily_cap.
              An open suspected flag escalates when the detector reports a proven-level signal, or (with
              proven_if_signal_while_throttled) a suspected-level signal from the events after the flag's
              opening call. The call that crosses a threshold is decided under the new state.
    commit()  after the call's log row is written, in the same transaction: opens or escalates the flag at
              that row with the evidence, and returns the alerts to raise once the transaction has committed.
    alerts    one error-level line per new or escalated flag and per refused retrieval of a suspended user.

Two calls that cross a threshold at the same moment are both decided "open" and both write their log row.
The partial unique index sweep_flags_one_open with ON CONFLICT ... DO NOTHING makes the second open wait for
the first transaction and then insert nothing: the second call's log row commits, its flag and alert are
dropped, and the user's next call is decided under the first call's flag.
"""

from dataclasses import dataclass, replace

from psycopg import AsyncConnection

from legal_search import events, flags
from legal_search.alerts import alert
from legal_search.caps import Caps
from legal_search.detector import Signal, assess
from legal_search.guard_settings import GuardSettings

Alert = tuple[str, dict]


@dataclass(frozen=True)
class Decision:
    caps: Caps | None            # the caps this call is served under; None: suspended, nothing is served
    refusal: str                 # the outcome logged when nothing can be served: capped | throttled | suspended
    level: str = 'none'          # the user's flag level after this call: none | suspected | proven
    change: str | None = None    # opened | escalated | None
    flag_id: int | None = None
    signals: tuple[Signal, ...] = ()

    @property
    def suspended(self) -> bool:
        return self.caps is None


async def decide(conn: AsyncConnection, settings: GuardSettings | None, caps: Caps, user: str,
                 attempt: events.Attempt) -> Decision:
    if settings is None:
        return Decision(caps, 'capped')
    flag = await flags.open_flag(conn, user)
    if flag is not None and flag.level == 'proven':
        return Decision(None, 'suspended', 'proven', flag_id=flag.id)
    after = await flags.watermark(conn, user)
    history, now = await events.load_user_events(conn, user, after, events.lookback(settings))
    verdict = assess([*history, attempt.event(now)], settings, now, flag.opened_log_id if flag else None)
    throttled = replace(caps, daily=min(caps.daily, settings.throttle_daily_cap))
    if verdict.level == 'proven':
        change = 'escalated' if flag is not None else 'opened'
        return Decision(None, 'suspended', 'proven', change, flag.id if flag else None, verdict.signals)
    if flag is not None:
        return Decision(throttled, 'throttled', 'suspected', flag_id=flag.id)
    if verdict.level == 'suspected':
        return Decision(throttled, 'throttled', 'suspected', 'opened', signals=verdict.signals)
    return Decision(caps, 'capped')


async def commit(conn: AsyncConnection, user: str, decision: Decision, log_id: int) -> list[Alert]:
    evidence = [signal.evidence() for signal in decision.signals]
    if decision.change == 'opened':
        flag = await flags.open_new(conn, user, decision.level, log_id, evidence)
        if flag is None:  # a concurrent call opened one first: this call's log row stays, nothing else
            return []
        return [('sweep_flag_opened', {'user_id': user, 'flag_id': flag.id, 'flag_level': flag.level,
                                       'log_id': log_id, 'signals': evidence})]
    if decision.change == 'escalated':
        flag = await flags.escalate(conn, decision.flag_id, log_id, evidence)
        if flag is None:  # cleared, or escalated by a concurrent call, since decide()
            return []
        return [('sweep_flag_escalated', {'user_id': user, 'flag_id': flag.id, 'flag_level': 'proven',
                                          'log_id': log_id, 'signals': evidence})]
    if decision.suspended:
        return [('sweep_refused', {'user_id': user, 'flag_id': decision.flag_id, 'flag_level': 'proven',
                                   'log_id': log_id})]
    return []


def raise_alerts(pending: list[Alert]) -> None:
    for event, fields in pending:
        alert(event, **fields)
