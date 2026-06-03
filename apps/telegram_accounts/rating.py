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


def _read_session_data(session_name: str) -> dict[str, object]:
    """Read useful data from the Pyrogram session SQLite file."""
    result: dict[str, object] = {
        "session_date": None,
        "peer_count": 0,
        "last_peer_update": None,
    }
    try:
        workdir = Path(settings.MEDIA_ROOT) / "telegram_runtime"
        path = workdir / f"{session_name}.session"
        if not path.exists():
            return result
        with sqlite3.connect(str(path)) as conn:
            row = conn.execute("SELECT date FROM sessions LIMIT 1").fetchone()
            if row and row[0]:
                result["session_date"] = datetime.fromtimestamp(int(row[0]), tz=dt_timezone.utc)
            try:
                peer_row = conn.execute(
                    "SELECT COUNT(*), MAX(last_update_on) FROM peers"
                ).fetchone()
                if peer_row:
                    result["peer_count"] = int(peer_row[0] or 0)
                    if peer_row[1]:
                        result["last_peer_update"] = datetime.fromtimestamp(
                            int(peer_row[1]), tz=dt_timezone.utc
                        )
            except Exception:
                pass
    except Exception:
        pass
    return result


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

    # Real Telegram account age
    session_data = _read_session_data(account.session_name)
    session_date = session_data["session_date"]
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

    # Peer count from session (organic activity indicator)
    peer_count = session_data["peer_count"]
    last_peer_update = session_data["last_peer_update"]
    days_since_peer_activity = None
    if last_peer_update:
        days_since_peer_activity = max(0, (
            now.replace(tzinfo=None) - last_peer_update.replace(tzinfo=None)
        ).days)

    events = list(account.health_events.order_by("-created_at")[:200])
    flood_waits = sum(1 for e in events if e.event_type == AccountHealthEvent.EventType.FLOOD_WAIT)
    spam_blocks = sum(1 for e in events if e.event_type == AccountHealthEvent.EventType.SPAM_BLOCK)
    successes = sum(1 for e in events if e.event_type == AccountHealthEvent.EventType.SUCCESS)

    # Activity pattern over last 30 days
    cutoff_30 = now - timedelta(days=30)
    recent_events = [e for e in events if e.created_at >= cutoff_30]
    active_days_last_30 = len({e.created_at.date() for e in recent_events if e.event_type == AccountHealthEvent.EventType.SUCCESS})

    # Days since last recorded activity
    days_since_last_success = None
    if account.last_success_at:
        days_since_last_success = max(0, (now - account.last_success_at).days)

    # Activity pattern quality
    if active_days_last_30 >= 20:
        activity_pattern = "регулярна (20+ днів/місяць)"
    elif active_days_last_30 >= 10:
        activity_pattern = "помірна (10-20 днів/місяць)"
    elif active_days_last_30 >= 3:
        activity_pattern = "нерегулярна (3-10 днів/місяць)"
    elif active_days_last_30 >= 1:
        activity_pattern = "рідкісна (1-2 дні/місяць)"
    else:
        activity_pattern = "відсутня (0 днів/місяць)"

    proxy = account.proxy
    proxy_ok = bool(proxy and proxy.status == "healthy")
    proxy_geo = getattr(proxy, "country", "") if proxy else ""

    has_username = bool(account.telegram_username)
    has_name = bool(account.first_name or account.last_name)
    has_phone = bool(account.phone_number)
    has_birth_date = bool(account.birth_date)
    profile_score = sum([has_username, has_name, has_phone, has_birth_date])

    # Use actual stored device/system, detect automation fingerprints
    from apps.telegram_accounts.services import DEVICE_PROFILE_POOL, RISKY_DEVICE_MODELS
    import random as _random
    raw_device = (account.device_model or "").strip()
    raw_system = (account.system_version or "").strip()
    device_is_risky = raw_device.lower() in RISKY_DEVICE_MODELS or not raw_device

    if device_is_risky and account.randomize_device_profile:
        # Pick and persist a real device now instead of waiting for next connection
        _random.seed(account.id)
        picked_device, picked_system = _random.choice(DEVICE_PROFILE_POOL)
        _random.seed()  # restore randomness
        TelegramAccount.objects.filter(pk=account.pk).update(
            device_model=picked_device,
            system_version=picked_system,
        )
        device = picked_device
        system = picked_system
        device_is_risky = False
    else:
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
        "peer_count": peer_count,
        "days_since_peer_activity": days_since_peer_activity,
        "active_days_last_30": active_days_last_30,
        "days_since_last_success": days_since_last_success,
        "activity_pattern": activity_pattern,
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

Поверни ТІЛЬКИ валідний JSON без markdown та без пояснень:
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
    "age":             {"score": <float 0-10>, "details": [<2-4 конкретних рядки українською>]},
    "identity":        {"score": <float 0-10>, "details": [<2-4 конкретних рядки українською>]},
    "network":         {"score": <float 0-10>, "details": [<2-4 конкретних рядки українською>]},
    "behavior":        {"score": <float 0-10>, "details": [<2-4 конкретних рядки українською>]},
    "block_history":   {"score": <float 0-10>, "details": [<2-4 конкретних рядки українською>]},
    "recovery_cycles": {"score": <float 0-10>, "details": [<1-3 конкретних рядки українською>]},
    "origin":          {"score": <float 0-10>, "details": [<2-4 конкретних рядки українською>]}
  },
  "recommendations": {
    "safe_modules": [<рядки українською>],
    "caution_modules": [<рядки українською>],
    "avoid": [<рядки українською>],
    "next_check_days": <int>,
    "warmup_needed": <bool>,
    "expected_lifetime_days": <int>
  },
  "analysis": "<2-3 речення пояснення рейтингу українською>"
}

Правила оцінки 7 факторів (вага у загальному score):
• age (18%) — вік акаунта: >5 років=9-10, 3-5 р=7-9, 1-3 р=5-7, 6-12 міс=3-5, <6 міс=1-3.
  details: [точний вік у днях/роках, оцінена дата реєстрації, активних днів у системі за 30 днів]

• identity (16%) — fingerprint+профіль: реальний Android/iOS без tdata-маркерів=7-10, підозрілий пристрій=1-5.
  КРИТИЧНО: якщо гео НОРМАЛЬНЕ (UA/EU/US) але пристрій підозрілий — обов'язково вказати "⚠ Нормальне гео але підозрілий fingerprint".
  details: [пристрій та ОС, username/ім'я статус, premium статус, tdata/автоматизаційні маркери]

• network (15%) — проксі+IP: резидентський proxy здоровий=8-10, немає proxy=4-6, proxy нездоровий=2-4.
  details: [наявність та тип proxy, гео proxy vs гео телефону, ризик прямого IP для автоматизації]

• behavior (14%) — активність: >100 операцій=8-10, 10-100=5-7, 1-10=3-5, 0=2-4.
  details: [кількість успішних операцій за весь час, коли остання дія, заповненість профілю, кількість діалогів]

• block_history (13%) — блокування: 0 подій=9-10, 1-3=6-8, 4-10=3-6, >10=1-3.
  details: [flood wait загалом, spam block загалом, health score, кількість подій за 30 днів]

• recovery_cycles (12%) — цикли: 0 спамблоків=10, 1=7, 2-3=4-6, >3=1-3.
  details: [скільки разів отримував spam block, чи зараз на карантині, поточний статус]

• origin (12%) — походження: відомий ринок+відповідне гео=8-10, невідповідність=4-6, підозріле=1-4.
  details: [країна по номеру телефону, гео proxy, джерело авторизації credentials/session, патерн реєстрації]

Загальний score = age×0.18 + identity×0.16 + network×0.15 + behavior×0.14 + block_history×0.13 + recovery_cycles×0.12 + origin×0.12
label: high≥7.0, medium 4.0-6.9, low<4.0
safe_modules: використовуй назви: нейрокоментинг, реакції, прогрів, парсинг каналів, парсинг повідомлень
"""


def _format_live_data(live: dict) -> str:
    """Format live Telegram API data block for the AI prompt."""
    if not live:
        return "- Дані з Telegram API: акаунт не підключений або отримати не вдалось\n\n"
    if "fetch_error" in live:
        return f"- Дані з Telegram API: помилка — {live['fetch_error']}\n\n"

    lines = ["📡 ДАНІ БЕЗПОСЕРЕДНЬО З TELEGRAM API (найточніші):"]

    last_seen = live.get("last_seen", "невідомо")
    lines.append(f"  • Останній раз онлайн: {last_seen}")

    if live.get("is_restricted"):
        reasons = ", ".join(live.get("restriction_reasons") or ["без деталей"])
        lines.append(f"  • ⚠ ОБМЕЖЕННЯ: {reasons}")
    else:
        lines.append("  • Обмеження/бани: відсутні ✓")

    if live.get("is_scam"):
        lines.append("  • 🚨 ПОЗНАЧЕНИЙ ЯК СКАМ")
    if live.get("is_fake"):
        lines.append("  • 🚨 ПОЗНАЧЕНИЙ ЯК ФЕЙК")

    lines.append(f"  • Telegram Premium: {'так ✓' if live.get('is_premium') else 'ні'}")
    has_bio = live.get("has_bio")
    bio_str = "є ✓" if has_bio else ("не вдалось отримати" if has_bio is None else "відсутня")
    lines.append(f"  • Біографія (bio): {bio_str}")

    dialogs = live.get("dialog_sample")
    if dialogs is not None:
        quality = "відмінно — акаунт активно використовується" if dialogs >= 50 else \
                  "добре" if dialogs >= 20 else \
                  "мало — можливо новий або малоактивний" if dialogs < 10 else "нормально"
        lines.append(f"  • Активних діалогів (перші 100): {dialogs} — {quality}")

    if live.get("settings_blocked"):
        lines.append("  • ⚠ Акаунт заблокував відправника")

    # SpamBot result
    spambot = live.get("spambot_status")
    if spambot == "clean":
        lines.append("  • @SpamBot: акаунт чистий — обмежень немає ✓")
    elif spambot == "spam_blocked":
        response_preview = live.get("spambot_response", "")[:120]
        lines.append(f"  • 🚨 @SpamBot: АКАУНТ У СПАМ-БАЗІ TELEGRAM — {response_preview}")
    elif spambot == "unknown":
        lines.append(f"  • @SpamBot: невідомий статус — {live.get('spambot_response', '')[:100]}")
    elif spambot == "no_response":
        lines.append("  • @SpamBot: немає відповіді")
    elif spambot == "check_failed":
        lines.append(f"  • @SpamBot: помилка перевірки — {live.get('spambot_error', '')[:80]}")

    return "\n".join(lines) + "\n\n"


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

    device_is_risky = features.get("device_is_risky", False)
    device_note = " ⚠ АВТОМАТИЗАЦІЙНИЙ ВІДБИТОК" if device_is_risky else ""

    # Device-geo mismatch: normal geo but suspicious device — explicit critical warning
    phone_geo = features.get("phone_prefix_geo", "")
    normal_geos = {"UA", "PL", "DE", "GB", "US", "FR", "IT", "ES", "NL", "CA", "AU"}
    device_geo_mismatch = (
        f"\n🚨 КРИТИЧНО: Гео акаунта ({phone_geo}) нормальне, але пристрій має ознаки автоматизації/tdata — "
        f"це підвищує ризик виявлення Telegram!"
        if device_is_risky and phone_geo in normal_geos else ""
    )

    # Last activity via our system
    inactivity = "немає даних"
    if features.get("days_since_last_success") is not None:
        d = features["days_since_last_success"]
        if d == 0:
            inactivity = "використовувався сьогодні через систему"
        elif d <= 3:
            inactivity = f"використовувався {d} дн. тому через систему"
        elif d <= 14:
            inactivity = f"не використовувався {d} днів через систему"
        else:
            inactivity = f"⚠ не використовувався {d} днів через систему"

    successes = features['successes']
    spam_blocks = features['spam_blocks']
    flood_waits = features['flood_waits']

    # Peer count from local Pyrogram cache
    peer_count = features.get('peer_count', 0)
    peer_note = (
        f"{peer_count} пірів у Pyrogram-кеші"
        if peer_count > 0
        else "Pyrogram-кеш порожній (не означає відсутність активності в реальному Telegram)"
    )

    # Age in years for readability
    age_days = features['age_days']
    age_years_note = f" (~{age_days // 365} р. {age_days % 365} дн.)" if age_days >= 365 else ""

    return (
        f"ПАРАМЕТРИ TELEGRAM АКАУНТА (відповідай виключно УКРАЇНСЬКОЮ мовою):\n\n"
        f"=== ВІК (age) ===\n"
        f"- Вік акаунта: {age_days} днів{age_years_note}{age_note}\n"
        f"- Telegram User ID: {features.get('telegram_user_id') or 'невідомо'}\n"
        f"- Активних днів у системі (30д): {features.get('active_days_last_30', 0)} — {features.get('activity_pattern', 'н/д')}\n"
        f"\n=== ІДЕНТИЧНІСТЬ (identity) ===\n"
        f"- Пристрій: {features['device_model']} / {features['system_version']}{device_note}\n"
        f"- Профіль: username={features['has_username']}, ім'я={features['has_name']}, "
        f"телефон={features['has_phone']} (повнота {features['profile_completeness']}/4)\n"
        f"- Кеш сесії: {peer_note}\n"
        f"{device_geo_mismatch}\n"
        f"\n=== МЕРЕЖА (network) ===\n"
        f"- Проксі: {proxy_str}\n"
        f"- Гео (телефон): {phone_geo} | Гео проксі: {features['proxy_geo'] or 'н/д'}\n"
        f"\n=== ПОВЕДІНКА (behavior) ===\n"
        f"- Успішних операцій через систему: {successes}\n"
        f"- Остання дія: {inactivity}\n"
        f"- Підключений зараз: {features['is_connected']}\n"
        f"\n=== ІСТОРІЯ БЛОКУВАНЬ (block_history) ===\n"
        f"- Flood wait: {flood_waits} | Spam block: {spam_blocks} | Health: {features['health_score']}/100\n"
        f"- На карантині: {features['is_quarantined']}\n"
        f"\n=== ЦИКЛИ ВІДНОВЛЕННЯ (recovery_cycles) ===\n"
        f"- Кількість spam block подій: {spam_blocks}\n"
        f"- На карантині зараз: {features['is_quarantined']}\n"
        f"\n=== ПОХОДЖЕННЯ (origin) ===\n"
        f"- Країна по номеру телефону: {phone_geo}\n"
        f"- Гео проксі: {features['proxy_geo'] or 'відсутнє'}\n"
        f"- Джерело авторизації: {features['auth_source']}\n"
        f"\n{_format_live_data(features.get('live', {}))}"
        f"Оціни цей акаунт за 7 факторами. ВСІ текстові поля JSON ОБОВ'ЯЗКОВО українською мовою."
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
            "max_tokens": 1600,
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
# Live Telegram API fetch
# ---------------------------------------------------------------------------


async def _fetch_live_telegram_data(app) -> dict:
    """Connect to Telegram and pull real account signals. Best-effort — never raises."""
    info: dict[str, object] = {}
    try:
        me = await app.get_me()
        info["is_restricted"] = bool(me.is_restricted)
        info["is_scam"] = bool(getattr(me, "is_scam", False))
        info["is_fake"] = bool(getattr(me, "is_fake", False))
        info["is_premium"] = bool(getattr(me, "is_premium", False))
        info["restriction_reasons"] = [r.reason for r in (me.restrictions or [])]

        # Status — Pyrogram 2.x uses pyrogram.enums.UserStatus enum; offline timestamp is user.last_online_date
        from pyrogram import enums as tg_enums
        status = getattr(me, "status", None)
        if status == tg_enums.UserStatus.ONLINE:
            info["last_seen"] = "онлайн зараз"
            info["last_seen_days"] = 0
        elif status == tg_enums.UserStatus.OFFLINE:
            was = getattr(me, "last_online_date", None)
            if was:
                if hasattr(was, "tzinfo") and was.tzinfo is None:
                    was = was.replace(tzinfo=dt_timezone.utc)
                total_secs = (datetime.now(tz=dt_timezone.utc) - was).total_seconds()
                hrs = max(0, int(total_secs // 3600))
                days = max(0, int(total_secs // 86400))
                if hrs < 1:
                    info["last_seen"] = "онлайн менше години тому"
                elif hrs < 24:
                    info["last_seen"] = f"онлайн {hrs} год. тому"
                else:
                    info["last_seen"] = f"онлайн {days} дн. тому"
                info["last_seen_days"] = days
            else:
                info["last_seen"] = "офлайн"
                info["last_seen_days"] = None
        elif status == tg_enums.UserStatus.RECENTLY:
            info["last_seen"] = "нещодавно (до 2 тижнів)"
            info["last_seen_days"] = 3
        elif status == tg_enums.UserStatus.LAST_WEEK:
            info["last_seen"] = "протягом тижня"
            info["last_seen_days"] = 7
        elif status == tg_enums.UserStatus.LAST_MONTH:
            info["last_seen"] = "протягом місяця"
            info["last_seen_days"] = 20
        elif status == tg_enums.UserStatus.LONG_AGO:
            info["last_seen"] = "давно (більше місяця)"
            info["last_seen_days"] = 60
        else:
            # None (bot) or unknown — session connected = recently active
            info["last_seen"] = "активний (сесія підключена)"
            info["last_seen_days"] = 0
    except Exception as e:
        info["fetch_error"] = str(e)
        return info

    # Bio via raw GetFullUser — most reliable
    try:
        from pyrogram.raw import functions, types as raw_types
        full_response = await app.invoke(
            functions.users.GetFullUser(id=raw_types.InputUserSelf())
        )
        full_user = full_response.full_user
        about = getattr(full_user, "about", None)
        info["has_bio"] = bool(about)
        info["bio_preview"] = (about or "")[:80] if about else ""
    except Exception:
        info["has_bio"] = None  # None = fetch failed (distinct from False = actually empty)

    # SpamBot check — real Telegram spam status via @SpamBot
    import asyncio
    try:
        await app.send_message("SpamBot", "/start")
        await asyncio.sleep(3)
        response_text = ""
        async for msg in app.get_chat_history("SpamBot", limit=3):
            if msg.from_user and msg.from_user.is_bot and msg.text:
                response_text = msg.text
                break
        if response_text:
            txt = response_text.lower()
            # Detect clean status (multi-language keywords)
            clean_keywords = ["no limits", "не обмежено", "не має обмежень", "good news",
                              "хороша новина", "не заблоковано", "without limitations"]
            spam_keywords = ["limited", "обмежено", "spam", "спам", "заблоковано",
                             "restricted", "unfortunately", "на жаль"]
            if any(k in txt for k in clean_keywords):
                info["spambot_status"] = "clean"
            elif any(k in txt for k in spam_keywords):
                info["spambot_status"] = "spam_blocked"
            else:
                info["spambot_status"] = "unknown"
            info["spambot_response"] = response_text[:300]
        else:
            info["spambot_status"] = "no_response"
    except Exception as e:
        info["spambot_status"] = "check_failed"
        info["spambot_error"] = str(e)

    # Dialog count — real usage indicator
    try:
        count = 0
        async for _ in app.get_dialogs(limit=100):
            count += 1
        info["dialog_sample"] = count
    except Exception:
        info["dialog_sample"] = None

    return info


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

        # Pull live data from Telegram if account is connected
        live_data: dict = {}
        if account.is_connected:
            from apps.telegram_accounts.services import run_client_operation
            try:
                live_data = run_client_operation(
                    account,
                    lambda app: _fetch_live_telegram_data(app),
                )
            except Exception as e:
                live_data = {"fetch_error": str(e)}

        features = _extract_features(account)
        features["live"] = live_data
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
        # Normalise factors: new format = {"age": {"score": x, "details": [...]}, ...}
        # Old format = {"age": 7.5, ...} — convert for backward compat
        raw_factors = result.get("factors") or {}
        normalised = {}
        for k, v in raw_factors.items():
            if isinstance(v, dict):
                normalised[k] = {"score": float(v.get("score", 0)), "details": list(v.get("details") or [])}
            else:
                normalised[k] = {"score": float(v or 0), "details": []}
        rating.factors = normalised
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
