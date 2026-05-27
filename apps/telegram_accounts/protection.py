"""Shared ai_protection utilities used by every automation module.

The original implementation lived in apps/neuro_commenting/services.py. It is
duplicated nowhere else — every module that wants the same behaviour should
import from here.

Usage from any job-bearing module:

    from apps.telegram_accounts import protection

    params = protection.protection_params(job)            # active profile dict
    cmin, cmax, emin, emax = protection.effective_delays_for(
        job,
        base_comment=(job.delay_min, job.delay_max),
        base_entry=(job.entry_min, job.entry_max),
    )
    if protection.in_quiet_hours(job): ...

The job object only needs two duck-typed attributes:
    - ai_protection: bool
    - protection_mode: str ("safe" / "balanced" / "fast")

Modules that don't (yet) have protection_mode still work — falls back to
"balanced".
"""

from __future__ import annotations

import random
import re
import time
from datetime import datetime, timedelta, timezone as dt_timezone

from django.utils import timezone


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

# Numbers are sourced from the published GramGPT profile table.
#
# - delay_multiplier   : scales caller-provided base delay ranges
# - comment_delay      : (min, max) seconds between consecutive actions (pre-multiplier)
# - entry_delay        : (min, max) seconds before first action in a new context
# - post_age_floor     : minimum age of a post before we act on it
# - skip_probability   : chance to drop a candidate even after filters matched
# - read_history_prob  : chance to scroll history before acting
# - typing_cpm         : (min, max) chars-per-minute typing simulation; None → off
# - typo_prob          : chance to ship a typo then edit
# - profile_view_prob  : chance to peek at the post author profile beforehand
# - self_delete_prob   : chance to delete our own message after some delay
# - quiet_hours        : (start, end) local-tz hours pause; None → off
# - scroll_depth       : (min, max) messages to read when scrolling
AI_PROTECTION_PROFILES: dict[str, dict[str, object]] = {
    "safe": {
        "delay_multiplier": 1.5,
        "comment_delay": (60.0, 180.0),
        "entry_delay": (90.0, 240.0),
        "post_age_floor": (90.0, 420.0),
        "skip_probability": 0.15,
        "read_history_prob": 0.50,
        "typing_cpm": (40, 60),
        "typo_prob": 0.08,
        "profile_view_prob": 0.90,
        "self_delete_prob": 0.03,
        "quiet_hours": (1, 7),
        "scroll_depth": (10, 30),
    },
    "balanced": {
        "delay_multiplier": 1.0,
        "comment_delay": (60.0, 180.0),
        "entry_delay": (90.0, 240.0),
        "post_age_floor": (60.0, 300.0),
        "skip_probability": 0.10,
        "read_history_prob": 0.30,
        "typing_cpm": (100, 150),
        "typo_prob": 0.05,
        "profile_view_prob": 0.70,
        "self_delete_prob": 0.02,
        "quiet_hours": (2, 7),
        "scroll_depth": (5, 20),
    },
    "fast": {
        "delay_multiplier": 0.7,
        "comment_delay": (60.0, 180.0),
        "entry_delay": (90.0, 240.0),
        "post_age_floor": (30.0, 120.0),
        "skip_probability": 0.05,
        "read_history_prob": 0.00,
        "typing_cpm": None,
        "typo_prob": 0.02,
        "profile_view_prob": 0.30,
        "self_delete_prob": 0.01,
        "quiet_hours": None,
        "scroll_depth": (5, 10),
    },
}


# Non-profile shared knobs.
BURST_WINDOW_MIN = 60
BURST_LIMIT = 15
TYPO_EDIT_DELAY = (3.0, 8.0)
SELF_DELETE_DELAY = (60.0, 300.0)


# ---------------------------------------------------------------------------
# Profile lookup
# ---------------------------------------------------------------------------


def protection_params(job) -> dict[str, object]:
    """Active profile parameters or {} if ai_protection is off / job lacks the flag.

    Accepts both `protection_mode` (new field used by neuro_commenting) and
    `speed_mode` (existing field used by reaction_bot / comment_parser /
    channel_parser) — they share the same SAFE/BALANCED/FAST keys, so the same
    profile dict applies to both."""
    if not getattr(job, "ai_protection", False):
        return {}
    mode = (
        getattr(job, "protection_mode", None)
        or getattr(job, "speed_mode", None)
        or "balanced"
    )
    return AI_PROTECTION_PROFILES.get(mode, AI_PROTECTION_PROFILES["balanced"])


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------


def random_delay(min_s: float, max_s: float) -> float:
    min_s = max(0.0, float(min_s))
    max_s = max(min_s, float(max_s))
    return random.uniform(min_s, max_s) if max_s > 0 else 0.0


def effective_delays_for(
    job,
    *,
    base_comment: tuple[float, float],
    base_entry: tuple[float, float],
) -> tuple[float, float, float, float]:
    """When ai_protection is on, override the caller's user-defined base ranges with
    the active profile's safe ranges scaled by delay_multiplier. When off, return the
    caller's ranges unchanged. Callers pass their own field-derived base ranges so we
    don't need to know the job's schema."""
    params = protection_params(job)
    if params:
        cmin, cmax = params["comment_delay"]  # type: ignore[index]
        emin, emax = params["entry_delay"]  # type: ignore[index]
        mult = float(params.get("delay_multiplier", 1.0))
        return cmin * mult, cmax * mult, emin * mult, emax * mult
    cmin, cmax = base_comment
    emin, emax = base_entry
    return cmin, cmax, emin, emax


def quiet_hours(job) -> tuple[int, int] | None:
    params = protection_params(job)
    return params.get("quiet_hours") if params else None  # type: ignore[return-value]


def in_quiet_hours(job, now: datetime | None = None) -> bool:
    window = quiet_hours(job)
    if window is None:
        return False
    now = now or timezone.localtime()
    start, end = window
    return start <= now.hour < end


def message_age_seconds(message) -> float:
    raw_date = getattr(message, "date", None)
    if raw_date is None:
        return 0.0
    if isinstance(raw_date, datetime):
        if raw_date.tzinfo is None:
            raw_date = raw_date.replace(tzinfo=dt_timezone.utc)
        return max(0.0, (datetime.now(tz=dt_timezone.utc) - raw_date).total_seconds())
    try:
        return max(0.0, time.time() - float(raw_date))
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Typing simulation
# ---------------------------------------------------------------------------

# Legacy "fast" fallback when ai_protection is off or the active profile disables typing.
LEGACY_TYPING_CHARS_PER_SECOND = 30
TYPING_MIN_SECONDS = 1.0
TYPING_MAX_SECONDS = 8.0


def typing_seconds(text: str, job=None) -> float:
    """Believable time-to-type for `text`. If the job's active profile defines
    typing_cpm, sample from that range; otherwise fall back to the legacy fast
    constant. Capped at 60s so a 500-char post can't stall a worker for minutes."""
    if not text:
        return TYPING_MIN_SECONDS
    cpm_range = None
    if job is not None:
        params = protection_params(job)
        cpm_range = params.get("typing_cpm") if params else None
    if cpm_range:
        cpm = random.uniform(*cpm_range)
        chars_per_second = max(0.5, cpm / 60.0)
        raw = len(text) / chars_per_second
        return min(60.0, max(TYPING_MIN_SECONDS, raw))
    raw = len(text) / LEGACY_TYPING_CHARS_PER_SECOND
    return min(TYPING_MAX_SECONDS, max(TYPING_MIN_SECONDS, raw))


# ---------------------------------------------------------------------------
# Typo injection
# ---------------------------------------------------------------------------

_KEYBOARD_NEIGHBORS = {
    "q": "wa", "w": "qeas", "e": "wrds", "r": "etdf", "t": "ryfg", "y": "tugh", "u": "yihj",
    "i": "uojk", "o": "ipkl", "p": "ol", "a": "qwsz", "s": "awedxz", "d": "sefcx",
    "f": "drtgvc", "g": "ftyhbv", "h": "gyujnb", "j": "huiknm", "k": "jiolm", "l": "kop",
    "z": "asx", "x": "zsdc", "c": "xdfv", "v": "cfgb", "b": "vghn", "n": "bhjm", "m": "njk",
    "й": "цф", "ц": "йук", "у": "цкв", "к": "уеа", "е": "кнг", "н": "егш", "г": "ншщ",
    "ш": "гщз", "щ": "шзх", "з": "щхї", "х": "зї", "ї": "зхж", "ф": "йві", "і": "віф",
    "в": "уаіп", "а": "впр", "п": "арс", "р": "псм", "с": "рмі", "м": "сіт", "т": "мь",
    "ь": "тб", "б": "ьюя", "ю": "бя", "я": "юч", "ч": "яс",
}


def inject_typo(text: str) -> str:
    """Replace one alphabetic character with a keyboard-adjacent one. Returns the
    input unchanged if no candidate position is found."""
    if not text or len(text) < 5:
        return text
    candidates = [
        (idx, ch) for idx, ch in enumerate(text)
        if ch.lower() in _KEYBOARD_NEIGHBORS
    ]
    if not candidates:
        return text
    idx, ch = random.choice(candidates)
    neighbour = random.choice(_KEYBOARD_NEIGHBORS[ch.lower()])
    if ch.isupper():
        neighbour = neighbour.upper()
    return text[:idx] + neighbour + text[idx + 1:]


# ---------------------------------------------------------------------------
# Profile-view telemetry
# ---------------------------------------------------------------------------


async def view_post_author(app, message, chat) -> bool:
    """Emit users.getFullUser / channels.getFullChannel so the action looks like it
    followed a profile click. Best-effort; never raises."""
    try:
        from_user = getattr(message, "from_user", None)
        if from_user is not None and getattr(from_user, "id", None):
            await app.get_users(from_user.id)
            return True
        sender_chat = getattr(message, "sender_chat", None)
        if sender_chat is not None and getattr(sender_chat, "id", None):
            await app.get_chat(sender_chat.id)
            return True
        async for _ in app.get_chat_members(chat.id, limit=random.randint(3, 8)):
            pass
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def normalize_source(raw_value: str):
    """Strip URL prefixes / @ from a Telegram channel reference. Returns int for raw
    chat IDs, str otherwise. Shared across modules that accept user-typed sources."""
    value = str(raw_value or "").strip()
    if not value:
        return ""
    if value.lstrip("-").isdigit():
        return int(value)
    value = re.sub(r"^https?://t\.me/", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^t\.me/", "", value, flags=re.IGNORECASE)
    value = value.lstrip("@").split("?")[0].split("/")[0].strip()
    return value or raw_value


def is_addlist_source(value: str) -> bool:
    return "addlist/" in str(value or "")


# ---------------------------------------------------------------------------
# Misc helpers callers commonly want
# ---------------------------------------------------------------------------


def burst_window_start() -> datetime:
    return timezone.now() - timedelta(minutes=BURST_WINDOW_MIN)


# ---------------------------------------------------------------------------
# Generic log analytics helper used by every module's overview_payload.
# ---------------------------------------------------------------------------


def log_event_stats(
    log_model,
    owner,
    *,
    window_hours: int = 24,
    account_label_field: str = "account__label",
    success_label: str = "success",
) -> dict:
    """Roll the last `window_hours` of a *Log model into a small analytics dict.

    Works with any module whose log model has:
        - owner FK
        - level (TextChoices with success/info/warning/error keys)
        - created_at
        - account FK (nullable, for per-account aggregation)
        - message text
    """
    from django.db.models import Count

    since = timezone.now() - timedelta(hours=window_hours)
    base = log_model.objects.filter(owner=owner, created_at__gte=since)

    level_buckets = base.values("level").annotate(n=Count("id")).order_by()
    by_level = {row["level"]: row["n"] for row in level_buckets}

    by_account = list(
        base.filter(level=success_label, account__isnull=False)
        .values("account_id", account_label_field)
        .annotate(events=Count("id"))
        .order_by("-events")[:20]
    )

    top_errors = list(
        base.filter(level__in=["error", "warning"])
        .values("message")
        .annotate(n=Count("id"))
        .order_by("-n")[:10]
    )

    return {
        "window_hours": window_hours,
        "total_events": base.count(),
        "successes": int(by_level.get("success", 0)),
        "warnings": int(by_level.get("warning", 0)),
        "errors": int(by_level.get("error", 0)),
        "infos": int(by_level.get("info", 0)),
        "by_account": by_account,
        "top_errors": top_errors,
    }
