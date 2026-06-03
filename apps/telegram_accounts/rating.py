"""GGR — AI-based Telegram account quality rating service.

Extracts account features, calls the configured OpenAI-compatible AI model,
and persists an AccountGGRRating record with score, survival predictions,
factor breakdown, and action recommendations.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

import requests
from django.conf import settings
from django.utils import timezone

from apps.telegram_accounts.models import AccountGGRRating, AccountHealthEvent, TelegramAccount


# ---------------------------------------------------------------------------
# Phone-prefix → country map (top Telegram markets)
# ---------------------------------------------------------------------------

_PREFIX_TO_GEO: list[tuple[str, str]] = [
    ("380", "UA"), ("375", "BY"), ("7", "RU"),
    ("48", "PL"), ("49", "DE"), ("44", "GB"),
    ("1", "US"), ("55", "BR"), ("52", "MX"),
    ("39", "IT"), ("34", "ES"), ("33", "FR"),
    ("90", "TR"), ("98", "IR"), ("62", "ID"),
    ("91", "IN"), ("86", "CN"), ("82", "KR"),
    ("81", "JP"), ("66", "TH"), ("84", "VN"),
    ("60", "MY"), ("63", "PH"), ("998", "UZ"),
    ("7", "KZ"), ("994", "AZ"), ("995", "GE"),
]


def _geo_from_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "").lstrip("0")
    for prefix, geo in sorted(_PREFIX_TO_GEO, key=lambda x: -len(x[0])):
        if digits.startswith(prefix):
            return geo
    return "XX"


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


def _read_session_date(session_name: str) -> datetime | None:
    """Read the authorization date from the Pyrogram session SQLite file."""
    try:
        workdir = Path(settings.MEDIA_ROOT) / "telegram_runtime"
        path = workdir / f"{session_name}.session"
        if not path.exists():
            return None
        with sqlite3.connect(str(path)) as conn:
            row = conn.execute("SELECT date FROM sessions LIMIT 1").fetchone()
            if row and row[0]:
                return datetime.fromtimestamp(int(row[0]), tz=dt_timezone.utc)
    except Exception:
        pass
    return None


def _estimate_age_from_user_id(user_id: int | None) -> int | None:
    """Estimate account age in days from Telegram user ID.
    Telegram user IDs are roughly sequential — higher ID = newer account."""
    if not user_id or user_id <= 0:
        return None
    # Approximate thresholds based on known Telegram ID milestones
    milestones = [
        (1_000_000,    "2013-04-01"),
        (10_000_000,   "2014-01-01"),
        (50_000_000,   "2015-01-01"),
        (100_000_000,  "2016-01-01"),
        (300_000_000,  "2017-06-01"),
        (500_000_000,  "2018-06-01"),
        (700_000_000,  "2019-06-01"),
        (1_000_000_000,"2020-06-01"),
        (1_500_000_000,"2021-03-01"),
        (2_000_000_000,"2021-09-01"),
        (3_000_000_000,"2022-06-01"),
        (5_000_000_000,"2023-06-01"),
        (7_000_000_000,"2024-03-01"),
    ]
    reg_date_str = "2013-01-01"
    for threshold, date_str in milestones:
        if user_id < threshold:
            break
        reg_date_str = date_str
    try:
        reg_date = datetime.strptime(reg_date_str, "%Y-%m-%d").replace(tzinfo=dt_timezone.utc)
        return max(0, (datetime.now(tz=dt_timezone.utc) - reg_date).days)
    except Exception:
        return None


def _extract_features(account: TelegramAccount) -> dict[str, object]:
    now = timezone.now()

    # Try real Telegram account age from session file, then user_id, then added_at
    session_date = _read_session_date(account.session_name)
    if session_date:
        age_days = max(0, (now.replace(tzinfo=None) - session_date.replace(tzinfo=None)).days)
        age_source = "session_file"
    else:
        estimated = _estimate_age_from_user_id(account.telegram_user_id)
        if estimated is not None:
            age_days = estimated
            age_source = "user_id_estimate"
        else:
            age_days = max(0, (now - account.created_at).days)
            age_source = "added_to_system"

    events = list(account.health_events.order_by("-created_at")[:100])
    flood_waits = sum(1 for e in events if e.event_type == AccountHealthEvent.EventType.FLOOD_WAIT)
    spam_blocks = sum(1 for e in events if e.event_type == AccountHealthEvent.EventType.SPAM_BLOCK)
    successes = sum(1 for e in events if e.event_type == AccountHealthEvent.EventType.SUCCESS)

    proxy = account.proxy
    proxy_ok = bool(proxy and proxy.status == "healthy")
    proxy_geo = getattr(proxy, "country", "") if proxy else ""

    has_username = bool(account.telegram_username)
    has_name = bool(account.first_name or account.last_name)
    has_phone = bool(account.phone_number)
    has_birth_date = bool(account.birth_date)
    profile_score = sum([has_username, has_name, has_phone, has_birth_date])

    # Use actual stored device/system, detect automation fingerprints
    from apps.telegram_accounts.services import RISKY_DEVICE_MODELS
    raw_device = (account.device_model or "").strip()
    raw_system = (account.system_version or "").strip()
    device_is_risky = raw_device.lower() in RISKY_DEVICE_MODELS or not raw_device
    device = raw_device if raw_device and not device_is_risky else "невідомий/автоматизація"
    system = raw_system if raw_system else "невідомо"

    phone_geo = _geo_from_phone(account.phone_number)
    geo = proxy_geo or phone_geo or "XX"

    is_quarantined = account.is_quarantined
    is_connected = account.is_connected
    health_score = account.health_score

    return {
        "age_days": age_days,
        "age_source": age_source,
        "telegram_user_id": account.telegram_user_id,
        "device_model": device,
        "system_version": system,
        "device_is_risky": device_is_risky,
        "has_proxy": bool(proxy),
        "proxy_healthy": proxy_ok,
        "proxy_geo": proxy_geo,
        "has_username": has_username,
        "has_name": has_name,
        "has_phone": has_phone,
        "profile_completeness": profile_score,
        "flood_waits": flood_waits,
        "spam_blocks": spam_blocks,
        "successes": successes,
        "is_quarantined": is_quarantined,
        "is_connected": is_connected,
        "health_score": health_score,
        "auth_source": account.source,
        "phone_prefix_geo": phone_geo,
        "geo": geo,
    }


# ---------------------------------------------------------------------------
# AI call
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """Ти — аналітик якості Telegram акаунтів для автоматизації. На основі параметрів акаунта видай JSON-рейтинг.

Поверни ТІЛЬКИ валідний JSON у точно такій структурі (без markdown, без пояснень):
{
  "score": <float 1.0-10.0>,
  "potential": <float 1.0-10.0>,
  "label": <"high"|"medium"|"low">,
  "survival_7d": <int 0-100>,
  "survival_30d": <int 0-100>,
  "median_lifetime_days": <int>,
  "geo": "<2-літерний код країни>",
  "similar_count": <int>,
  "similar_params": "<стислий опис схожих акаунтів українською>",
  "factors": {
    "age": <float 0-10>,
    "device": <float 0-10>,
    "proxy": <float 0-10>,
    "profile": <float 0-10>,
    "health_history": <float 0-10>,
    "registration": <float 0-10>
  },
  "recommendations": {
    "safe_modules": [<список рядків українською>],
    "caution_modules": [<список рядків українською>],
    "avoid": [<список рядків українською>],
    "next_check_days": <int>,
    "warmup_needed": <bool>,
    "expected_lifetime_days": <int>
  },
  "analysis": "<2-3 речення пояснення рейтингу українською мовою>"
}

Правила оцінки:
- score: загальна якість акаунта для автоматизації (стійкість до бану, довговічність)
- potential: наскільки добре він може працювати ЯКЩО виживе
- label: high=7+, medium=4-7, low<4
- survival_7d/30d: % шанс що акаунт залишиться живим і придатним через 7/30 днів при помірній автоматизації
- median_lifetime_days: очікувана кількість днів до першого серйозного обмеження
- factors: субоцінки що пояснюють загальний score
- safe_modules: модулі які безпечно запускати (використовуй: нейрокоментинг, реакції, прогрів, парсинг)
- caution_modules: модулі що потребують обмеженого навантаження
- avoid: конкретні ризиковані дії яких треба уникати
- warmup_needed: чи рекомендується прогрів 3-7 днів перед автоматизацією
- Вік акаунта >2 років значно підвищує score. Відсутність проксі і device-fingerprint типу автоматизації знижує його.
"""

_USER_TEMPLATE = """Account parameters:
- Age: {age_days} days old
- Device: {device_model} / {system_version}
- Proxy: {"assigned and healthy" if has_proxy and proxy_healthy else "assigned but unhealthy" if has_proxy else "no proxy"}
- Geo (phone): {phone_prefix_geo} | Proxy geo: {proxy_geo or "n/a"}
- Profile: username={has_username}, name={has_name}, phone={has_phone} (completeness {profile_completeness}/3)
- Health events (last 100): {flood_waits} flood waits, {spam_blocks} spam blocks, {successes} successes
- Internal health score: {health_score}/100
- Quarantined: {is_quarantined}
- Connected: {is_connected}
- Auth source: {auth_source}

Rate this account."""


def _build_user_message(features: dict[str, object]) -> str:
    if features["has_proxy"] and features["proxy_healthy"]:
        proxy_str = "є, резидентський, здоровий"
    elif features["has_proxy"]:
        proxy_str = "є, але нездоровий"
    else:
        proxy_str = "відсутній (прямий IP)"

    age_note = {
        "session_file": " (з session файлу — точно)",
        "user_id_estimate": " (оцінка по Telegram User ID)",
        "added_to_system": " (дата додавання в систему — НЕ реальний вік акаунта!)",
    }.get(features.get("age_source", ""), "")

    device_note = " ⚠ АВТОМАТИЗАЦІЙНИЙ ВІДБИТОК" if features.get("device_is_risky") else ""

    return (
        f"ПАРАМЕТРИ TELEGRAM АКАУНТА (відповідай виключно УКРАЇНСЬКОЮ мовою):\n\n"
        f"- Вік акаунта: {features['age_days']} днів{age_note}\n"
        f"- Telegram User ID: {features.get('telegram_user_id') or 'невідомо'}\n"
        f"- Пристрій: {features['device_model']} / {features['system_version']}{device_note}\n"
        f"- Проксі: {proxy_str}\n"
        f"- Гео (телефон): {features['phone_prefix_geo']} | Гео проксі: {features['proxy_geo'] or 'н/д'}\n"
        f"- Профіль: username={features['has_username']}, ім'я={features['has_name']}, "
        f"телефон={features['has_phone']} (повнота {features['profile_completeness']}/4)\n"
        f"- Події здоров'я (останні 100): {features['flood_waits']} flood wait, "
        f"{features['spam_blocks']} spam block, {features['successes']} успішних\n"
        f"- Внутрішній health score: {features['health_score']}/100\n"
        f"- На карантині: {features['is_quarantined']}\n"
        f"- Підключений: {features['is_connected']}\n"
        f"- Джерело авторизації: {features['auth_source']}\n\n"
        f"Оціни цей акаунт. ВСІ текстові поля JSON ОБОВ'ЯЗКОВО українською мовою."
    )


def _call_ai(features: dict[str, object]) -> dict[str, object]:
    base_url = (getattr(settings, "PROFILE_TEXT_BASE_URL", "") or "").rstrip("/")
    api_key = getattr(settings, "PROFILE_TEXT_API_KEY", "") or ""
    model = getattr(settings, "PROFILE_TEXT_MODEL", "") or "gpt-4o-mini"

    if not base_url or not api_key:
        raise RuntimeError("PROFILE_TEXT_BASE_URL / PROFILE_TEXT_API_KEY не налаштовані")

    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_message(features)},
            ],
            "temperature": 0.0,
            "max_tokens": 800,
            "stream": False,
        },
        timeout=60,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    return json.loads(raw)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_ggr_rating(rating_id: int) -> AccountGGRRating:
    """Execute GGR analysis for a pending AccountGGRRating record."""
    rating = AccountGGRRating.objects.select_related("account__proxy").get(pk=rating_id)
    rating.status = AccountGGRRating.Status.RUNNING
    rating.save(update_fields=["status", "updated_at"])

    try:
        account = (
            TelegramAccount.objects
            .select_related("proxy")
            .prefetch_related("health_events")
            .get(pk=rating.account_id)
        )
        features = _extract_features(account)
        result = _call_ai(features)

        score = float(result.get("score", 5.0))
        potential = float(result.get("potential", 5.0))
        score = max(1.0, min(10.0, score))
        potential = max(1.0, min(10.0, potential))

        label_raw = str(result.get("label", "medium")).lower()
        if label_raw not in ("high", "medium", "low"):
            label_raw = "high" if score >= 7 else "medium" if score >= 4 else "low"

        rating.score = round(score, 1)
        rating.potential = round(potential, 1)
        rating.label = label_raw
        rating.survival_7d = int(result.get("survival_7d") or 0)
        rating.survival_30d = int(result.get("survival_30d") or 0)
        rating.median_lifetime_days = int(result.get("median_lifetime_days") or 0)
        rating.geo = str(result.get("geo") or features.get("geo") or "")[:4]
        rating.similar_count = int(result.get("similar_count") or 0)
        rating.similar_params = str(result.get("similar_params") or "")[:255]
        rating.factors = result.get("factors") or {}
        rating.recommendations = result.get("recommendations") or {}
        rating.analysis = str(result.get("analysis") or "")
        rating.error = ""
        rating.status = AccountGGRRating.Status.DONE

    except Exception as exc:
        rating.error = str(exc)
        rating.status = AccountGGRRating.Status.FAILED

    rating.save()
    return rating


def create_ggr_rating(account: TelegramAccount) -> AccountGGRRating:
    """Create a pending rating record. The caller must dispatch the Celery task."""
    return AccountGGRRating.objects.create(
        account=account,
        owner=account.owner,
        status=AccountGGRRating.Status.PENDING,
    )
