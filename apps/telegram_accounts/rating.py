"""GGR — AI-based Telegram account quality rating service.

Extracts account features, calls the configured OpenAI-compatible AI model,
and persists an AccountGGRRating record with score, survival predictions,
factor breakdown, and action recommendations.
"""
from __future__ import annotations

import json
import re
from datetime import timedelta

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


def _extract_features(account: TelegramAccount) -> dict[str, object]:
    now = timezone.now()

    age_days = max(0, (now - account.created_at).days)

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
    profile_score = sum([has_username, has_name, has_phone])

    device = (account.device_model or "").strip()
    system = (account.system_version or "").strip()

    phone_geo = _geo_from_phone(account.phone_number)
    geo = proxy_geo or phone_geo or "XX"

    is_quarantined = account.is_quarantined
    is_connected = account.is_connected
    health_score = account.health_score

    return {
        "age_days": age_days,
        "device_model": device or "unknown",
        "system_version": system or "unknown",
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
    has_proxy = features["has_proxy"]
    proxy_healthy = features["proxy_healthy"]
    if has_proxy and proxy_healthy:
        proxy_str = "assigned and healthy"
    elif has_proxy:
        proxy_str = "assigned but unhealthy"
    else:
        proxy_str = "no proxy"

    return (
        f"Account parameters:\n"
        f"- Age: {features['age_days']} days old\n"
        f"- Device: {features['device_model']} / {features['system_version']}\n"
        f"- Proxy: {proxy_str}\n"
        f"- Geo (phone): {features['phone_prefix_geo']} | Proxy geo: {features['proxy_geo'] or 'n/a'}\n"
        f"- Profile: username={features['has_username']}, name={features['has_name']}, "
        f"phone={features['has_phone']} (completeness {features['profile_completeness']}/3)\n"
        f"- Health events (last 100): {features['flood_waits']} flood waits, "
        f"{features['spam_blocks']} spam blocks, {features['successes']} successes\n"
        f"- Internal health score: {features['health_score']}/100\n"
        f"- Quarantined: {features['is_quarantined']}\n"
        f"- Connected: {features['is_connected']}\n"
        f"- Auth source: {features['auth_source']}\n\n"
        f"Rate this account."
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
