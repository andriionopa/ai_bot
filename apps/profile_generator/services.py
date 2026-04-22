from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.profile_generator.models import ProfileDraft
from apps.input_validation import validate_image_bytes, validate_uploaded_image
from apps.telegram_accounts.models import AccountHealthEvent, TelegramAccount
from apps.telegram_accounts.services import (
    get_account_runtime_block_reason,
    register_account_runtime_event,
    run_client_operation,
)
from workers.telegram_runtime.guard import classify_runtime_exception


class ProfileProviderError(RuntimeError):
    pass


COUNTRY_LANGUAGE_HINTS = {
    "ukraine": "Ukrainian",
    "україна": "Ukrainian",
    "украина": "Ukrainian",
    "usa": "English",
    "united states": "English",
    "america": "English",
    "canada": "English",
    "uk": "English",
    "united kingdom": "English",
    "poland": "Polish",
    "польща": "Polish",
    "germany": "German",
    "deutschland": "German",
    "france": "French",
    "spain": "Spanish",
    "italy": "Italian",
    "turkey": "Turkish",
    "brazil": "Portuguese",
    "portugal": "Portuguese",
    "russia": "Russian",
    "россия": "Russian",
}


def _provider_url(base_url: str, endpoint: str) -> str:
    if not base_url:
        raise ProfileProviderError("Profile provider base URL is not configured.")
    if base_url.rstrip("/").endswith(endpoint.strip("/")):
        return base_url
    return urljoin(f"{base_url.rstrip('/')}/", endpoint.strip("/"))


def _provider_headers(api_key: str) -> dict[str, str]:
    if not api_key:
        raise ProfileProviderError("Profile provider API key is not configured.")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def infer_country_language(country: str) -> str:
    normalized = country.strip().lower()
    return COUNTRY_LANGUAGE_HINTS.get(normalized, f"the main local language of {country}")


def draft_age(draft: ProfileDraft) -> int:
    if draft.birth_date:
        today = timezone.localdate()
        return today.year - draft.birth_date.year - (
            (today.month, today.day) < (draft.birth_date.month, draft.birth_date.day)
        )
    return draft.age or 25


def _is_crypto_niche(profession: str) -> bool:
    normalized = profession.lower()
    return any(keyword in normalized for keyword in ("crypto", "крипто", "cryptocurrency", "trading", "трейдинг"))


def _channel_cta(draft: ProfileDraft) -> str:
    channel = draft.telegram_channel.strip()
    language = infer_country_language(draft.country)
    if _is_crypto_niche(draft.profession):
        if language == "Ukrainian":
            return f"Безкоштовні дропи/сигнали {channel}"
        if language == "Russian":
            return f"Бесплатные дропы/сигналы {channel}"
        return f"Free drops/signals {channel}"
    if language == "Ukrainian":
        return f"Більше тут {channel}"
    return f"More here {channel}"


def finalize_telegram_bio(draft: ProfileDraft, bio: str) -> str:
    bio = " ".join(bio.strip().strip('"').split())
    channel = draft.telegram_channel.strip()
    if channel and channel not in bio:
        bio = _channel_cta(draft)
    if channel and len(bio) > 70 and channel in bio:
        prefix_limit = max(0, 69 - len(channel))
        prefix = bio.replace(channel, "").strip()[:prefix_limit].strip()
        bio = f"{prefix} {channel}".strip()
    return bio[:70]


def _response_preview(response: requests.Response) -> str:
    body = (response.text or "").strip().replace("\n", " ")
    if not body:
        return "<empty body>"
    return body[:300]


def _provider_json(response: requests.Response, *, provider_name: str) -> dict[str, object]:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise ProfileProviderError(
            f"{provider_name} provider HTTP {response.status_code}: {_response_preview(response)}"
        ) from exc

    try:
        return response.json()
    except json.JSONDecodeError as exc:
        content_type = response.headers.get("content-type", "unknown")
        if "text/event-stream" in content_type:
            return _parse_openai_event_stream(response.text, provider_name=provider_name)
        raise ProfileProviderError(
            f"{provider_name} provider returned non-JSON response "
            f"(status={response.status_code}, content-type={content_type}): {_response_preview(response)}"
        ) from exc


def _parse_openai_event_stream(raw: str, *, provider_name: str) -> dict[str, object]:
    chunks: list[str] = []
    final_payload: dict[str, object] | None = None

    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line.removeprefix("data:").strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue

        final_payload = event
        choices = event.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        if not isinstance(choice, dict):
            continue

        delta = choice.get("delta") or {}
        message = choice.get("message") or {}
        if isinstance(delta, dict) and delta.get("content"):
            chunks.append(str(delta["content"]))
        elif isinstance(message, dict) and message.get("content"):
            chunks.append(str(message["content"]))

    content = "".join(chunks).strip()
    if content:
        return {"choices": [{"message": {"content": content}}]}

    if final_payload is not None:
        return final_payload

    raise ProfileProviderError(f"{provider_name} provider returned an empty event stream.")


def build_bio_prompt(draft: ProfileDraft) -> str:
    language = infer_country_language(draft.country)
    age = draft_age(draft)
    channel = draft.telegram_channel.strip()
    return (
        "Create one Telegram profile bio that will be pasted into Telegram Profile -> Bio/About. "
        "Return only the bio text. Max 70 characters. No quotes, no markdown. "
        f"Write in {language}. "
        f"Person: {age} years old, gender: {draft.gender}, country: {draft.country}. "
        f"Profession/niche: {draft.profession}. "
        f"Include this Telegram channel exactly: {channel}. "
        "Make it a short CTA related to the niche. "
        "If the niche is cryptocurrency/crypto/trading, mention free drops/signals."
    )


def build_photo_prompt(draft: ProfileDraft) -> str:
    age = draft_age(draft)
    return (
        "Realistic casual profile photo/selfie, natural light, smartphone camera, "
        "not celebrity, not studio, no text, no watermark. "
        f"{age} year old {draft.gender} person from {draft.country}, "
        f"profession vibe: {draft.profession}."
    )


def generate_bio_text(draft: ProfileDraft) -> str:
    url = _provider_url(settings.PROFILE_TEXT_BASE_URL, "/chat/completions")
    payload = {
        "model": settings.PROFILE_TEXT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You generate short, realistic social profile bios.",
            },
            {"role": "user", "content": build_bio_prompt(draft)},
        ],
        "temperature": 0.8,
        "max_tokens": 60,
        "stream": False,
    }
    response = requests.post(
        url,
        headers=_provider_headers(settings.PROFILE_TEXT_API_KEY),
        json=payload,
        timeout=settings.PROFILE_PROVIDER_TIMEOUT_SECONDS,
    )
    data = _provider_json(response, provider_name="Text")
    try:
        bio = data["choices"][0]["message"]["content"].strip().strip('"')
    except (KeyError, IndexError, TypeError) as exc:
        raise ProfileProviderError("Text provider returned an unsupported response.") from exc
    return finalize_telegram_bio(draft, bio)


def _save_image_from_response(draft: ProfileDraft, data: dict[str, object]) -> None:
    image_data = (data.get("data") or [{}])[0]
    if not isinstance(image_data, dict):
        raise ProfileProviderError("Image provider returned an unsupported response.")

    filename = f"profile-{draft.id}-{slugify(draft.profession) or 'photo'}.png"
    if image_data.get("b64_json"):
        try:
            content = base64.b64decode(str(image_data["b64_json"]), validate=True)
            validate_image_bytes(content)
        except (ValueError, ValidationError) as exc:
            raise ProfileProviderError(str(exc)) from exc
        draft.photo.save(filename, ContentFile(content), save=False)
        return

    if image_data.get("url"):
        image_response = requests.get(str(image_data["url"]), timeout=settings.PROFILE_PROVIDER_TIMEOUT_SECONDS)
        image_response.raise_for_status()
        try:
            validate_image_bytes(image_response.content)
        except ValidationError as exc:
            raise ProfileProviderError(str(exc)) from exc
        draft.photo.save(filename, ContentFile(image_response.content), save=False)
        return

    raise ProfileProviderError("Image provider response has neither b64_json nor url.")


def generate_profile_photo(draft: ProfileDraft) -> ProfileDraft:
    url = _provider_url(settings.PROFILE_IMAGE_BASE_URL, "/images/generations")
    prompt = build_photo_prompt(draft)
    payload = {
        "model": settings.PROFILE_IMAGE_MODEL,
        "prompt": prompt,
        "size": settings.PROFILE_IMAGE_SIZE,
        "n": 1,
    }
    response = requests.post(
        url,
        headers=_provider_headers(settings.PROFILE_IMAGE_API_KEY),
        json=payload,
        timeout=settings.PROFILE_PROVIDER_TIMEOUT_SECONDS,
    )
    data = _provider_json(response, provider_name="Image")
    _save_image_from_response(draft, data)
    draft.photo_prompt = prompt
    draft.image_source = ProfileDraft.ImageSource.AI
    draft.provider_payload = {"image_model": settings.PROFILE_IMAGE_MODEL, "image_size": settings.PROFILE_IMAGE_SIZE}
    draft.status = ProfileDraft.Status.GENERATED
    draft.last_error = ""
    draft.save(
        update_fields=[
            "photo",
            "photo_prompt",
            "image_source",
            "provider_payload",
            "status",
            "last_error",
            "updated_at",
        ]
    )
    return draft


@transaction.atomic
def generate_profile_bio(draft: ProfileDraft) -> ProfileDraft:
    try:
        draft.bio = generate_bio_text(draft)
        draft.status = ProfileDraft.Status.GENERATED
        draft.last_error = ""
        draft.provider_payload = {
            **draft.provider_payload,
            "text_model": settings.PROFILE_TEXT_MODEL,
        }
        draft.save(update_fields=["bio", "status", "last_error", "provider_payload", "updated_at"])
    except Exception as exc:
        draft.mark_failed(str(exc))
    return draft


@transaction.atomic
def upload_profile_photo(draft: ProfileDraft, photo) -> ProfileDraft:
    validate_uploaded_image(photo)
    draft.photo = photo
    draft.image_source = ProfileDraft.ImageSource.UPLOAD
    draft.status = ProfileDraft.Status.GENERATED
    draft.last_error = ""
    draft.save(update_fields=["photo", "image_source", "status", "last_error", "updated_at"])
    return draft


@transaction.atomic
def apply_profile_draft(draft: ProfileDraft) -> ProfileDraft:
    account = TelegramAccount.objects.select_for_update().get(pk=draft.account_id)
    block_reason = get_account_runtime_block_reason(account)
    if block_reason:
        draft.mark_failed(block_reason)
        return draft
    if not draft.bio and not draft.photo:
        draft.mark_failed("Bio or photo is required before applying profile.")
        return draft

    try:
        async def apply_operation(app):
            if draft.bio:
                await app.update_profile(bio=draft.bio)
            if draft.photo:
                await app.set_profile_photo(photo=str(Path(draft.photo.path)))
            return True

        run_client_operation(account, apply_operation)
        register_account_runtime_event(
            account,
            event_type=AccountHealthEvent.EventType.SUCCESS,
            metadata={"source": "profile_generator", "draft_id": draft.id},
        )
        if draft.birth_date and account.birth_date != draft.birth_date:
            account.birth_date = draft.birth_date
            account.save(update_fields=["birth_date"])
        draft.mark_applied()
    except Exception as exc:
        classified = classify_runtime_exception(exc)
        if classified is not None:
            event_type, metadata = classified
            register_account_runtime_event(account, event_type=event_type, metadata=metadata)
        draft.mark_failed(str(exc))
    return draft
