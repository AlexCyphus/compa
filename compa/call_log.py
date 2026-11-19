"""What happened on a call: each learner turn with its timing and feedback."""
import time
from dataclasses import dataclass, field

from compa.brain import Feedback, Reply


@dataclass
class TurnRecord:
    learner: str
    seconds: float = 0.0
    reply_after_seconds: float | None = None
    speculation_used: bool = False
    feedback: Feedback | None = None
    reply: Reply | None = None
    ended_at: float = field(default_factory=time.monotonic)


@dataclass
class CallLog:
    turns: list[TurnRecord] = field(default_factory=list)
    interruptions: int = 0
