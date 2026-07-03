import base64
import json
from datetime import date
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.profile_generator.models import ProfileDraft
from apps.profile_generator.services import build_bio_prompt
from apps.telegram_accounts.models import AccountHealthEvent, TelegramAccount


VALID_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.django_db
def test_profile_generator_dashboard_requires_authenticated_user():
    response = Client().get("/dashboard/profiles/")

    assert response.status_code == 302
    assert response.headers["Location"] == "http://127.0.0.1:3001/"


@pytest.mark.django_db
def test_create_profile_draft_with_manual_photo():
    user = get_user_model().objects.create_user(email="profiles@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Profile Account",
        session_name="profile-account",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/profiles/drafts/",
        {
            "account": account.id,
            "gender": ProfileDraft.Gender.FEMALE,
            "birth_date": "1998-04-21",
            "country": "Ukraine",
            "profession": "designer",
            "telegram_channel": "@design_channel",
            "bio": "Design, coffee, slow mornings",
            "photo": SimpleUploadedFile("profile.png", VALID_PNG, content_type="image/png"),
        },
    )

    assert response.status_code == 201
    draft = ProfileDraft.objects.get(pk=response.json()["id"])
    assert draft.owner == user
    assert draft.birth_date == date(1998, 4, 21)
    assert draft.telegram_channel == "@design_channel"
    assert draft.image_source == ProfileDraft.ImageSource.UPLOAD
    assert draft.status == ProfileDraft.Status.GENERATED


@pytest.mark.django_db
def test_create_profile_draft_rejects_non_image_upload():
    user = get_user_model().objects.create_user(email="bad-upload@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Bad Upload",
        session_name="bad-upload",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/profiles/drafts/",
        {
            "account": account.id,
            "gender": ProfileDraft.Gender.FEMALE,
            "birth_date": "1998-04-21",
            "country": "Ukraine",
            "profession": "designer",
            "telegram_channel": "@design_channel",
            "photo": SimpleUploadedFile("payload.png", b"not an image", content_type="image/png"),
        },
    )

    assert response.status_code == 400
    assert not ProfileDraft.objects.filter(owner=user).exists()


@pytest.mark.django_db
def test_generate_bio_endpoint_updates_draft(monkeypatch, settings):
    settings.PROFILE_TEXT_BASE_URL = "https://text-provider.test/v1"
    settings.PROFILE_TEXT_API_KEY = "token"
    settings.PROFILE_TEXT_MODEL = "text-model"

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "Creative designer from Kyiv"}}]}

    def fake_post(*args, **kwargs):
        assert args[0] == "https://text-provider.test/v1/chat/completions"
        return FakeResponse()

    monkeypatch.setattr("apps.profile_generator.services.requests.post", fake_post)
    user = get_user_model().objects.create_user(email="bio@example.com", password="pass")
    account = TelegramAccount.objects.create(owner=user, label="Bio Account", session_name="bio-account")
    draft = ProfileDraft.objects.create(
        owner=user,
        account=account,
        gender=ProfileDraft.Gender.MALE,
        birth_date=date(1994, 4, 21),
        country="Ukraine",
        profession="designer",
        telegram_channel="@design_channel",
    )
    client = Client()
    client.force_login(user)

    response = client.post(f"/api/v1/profiles/drafts/{draft.id}/generate-bio/")

    assert response.status_code == 200
    draft.refresh_from_db()
    assert draft.bio == "Більше тут @design_channel"
    assert draft.status == ProfileDraft.Status.GENERATED


@pytest.mark.django_db
def test_bio_prompt_uses_country_language_channel_and_crypto_cta():
    user = get_user_model().objects.create_user(email="prompt@example.com", password="pass")
    account = TelegramAccount.objects.create(owner=user, label="Prompt Account", session_name="prompt-account")
    draft = ProfileDraft.objects.create(
        owner=user,
        account=account,
        gender=ProfileDraft.Gender.MALE,
        birth_date=date(1995, 4, 21),
        country="Ukraine",
        profession="cryptocurrency",
        telegram_channel="@crypto_drops",
    )

    prompt = build_bio_prompt(draft)

    assert "Ukrainian" in prompt
    assert "@crypto_drops" in prompt
    assert "free drops/signals" in prompt


@pytest.mark.django_db
def test_generate_bio_reports_non_json_provider_response(monkeypatch, settings):
    settings.PROFILE_TEXT_BASE_URL = "https://text-provider.test/v1"
    settings.PROFILE_TEXT_API_KEY = "token"
    settings.PROFILE_TEXT_MODEL = "text-model"

    class FakeResponse:
        status_code = 200
        text = ""
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            return None

        def json(self):
            raise json.JSONDecodeError("Expecting value", "", 0)

    monkeypatch.setattr("apps.profile_generator.services.requests.post", lambda *args, **kwargs: FakeResponse())
    user = get_user_model().objects.create_user(email="bad-provider@example.com", password="pass")
    account = TelegramAccount.objects.create(owner=user, label="Bad Provider", session_name="bad-provider")
    draft = ProfileDraft.objects.create(
        owner=user,
        account=account,
        gender=ProfileDraft.Gender.MALE,
        birth_date=date(1994, 4, 21),
        country="Ukraine",
        profession="designer",
        telegram_channel="@design_channel",
    )
    client = Client()
    client.force_login(user)

    response = client.post(f"/api/v1/profiles/drafts/{draft.id}/generate-bio/")

    assert response.status_code == 200
    draft.refresh_from_db()
    assert draft.status == ProfileDraft.Status.FAILED
    assert "Text provider returned non-JSON response" in draft.last_error


@pytest.mark.django_db
def test_generate_bio_accepts_openai_event_stream(monkeypatch, settings):
    settings.PROFILE_TEXT_BASE_URL = "https://text-provider.test/v1"
    settings.PROFILE_TEXT_API_KEY = "token"
    settings.PROFILE_TEXT_MODEL = "text-model"

    class FakeResponse:
        status_code = 200
        text = "\n".join(
            [
                'data: {"choices":[{"delta":{"role":"assistant","content":"Creative"}}]}',
                'data: {"choices":[{"delta":{"content":" designer from Kyiv"}}]}',
                "data: [DONE]",
            ]
        )
        headers = {"content-type": "text/event-stream"}

        def raise_for_status(self):
            return None

        def json(self):
            raise json.JSONDecodeError("Expecting value", self.text, 0)

    monkeypatch.setattr("apps.profile_generator.services.requests.post", lambda *args, **kwargs: FakeResponse())
    user = get_user_model().objects.create_user(email="stream-provider@example.com", password="pass")
    account = TelegramAccount.objects.create(owner=user, label="Stream Provider", session_name="stream-provider")
    draft = ProfileDraft.objects.create(
        owner=user,
        account=account,
        gender=ProfileDraft.Gender.FEMALE,
        birth_date=date(1997, 4, 21),
        country="Ukraine",
        profession="designer",
        telegram_channel="@design_channel",
    )
    client = Client()
    client.force_login(user)

    response = client.post(f"/api/v1/profiles/drafts/{draft.id}/generate-bio/")

    assert response.status_code == 200
    draft.refresh_from_db()
    assert draft.status == ProfileDraft.Status.GENERATED
    assert draft.bio == "Більше тут @design_channel"


@pytest.mark.django_db
def test_generate_photo_endpoint_saves_ai_photo(monkeypatch, settings):
    settings.PROFILE_IMAGE_BASE_URL = "https://image-provider.test/v1"
    settings.PROFILE_IMAGE_API_KEY = "image-token"
    settings.PROFILE_IMAGE_MODEL = "image-model"

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(VALID_PNG).decode("ascii")}]}

    monkeypatch.setattr("apps.profile_generator.services.requests.post", lambda *args, **kwargs: FakeResponse())
    user = get_user_model().objects.create_user(email="photo@example.com", password="pass")
    account = TelegramAccount.objects.create(owner=user, label="Photo Account", session_name="photo-account")
    draft = ProfileDraft.objects.create(
        owner=user,
        account=account,
        gender=ProfileDraft.Gender.FEMALE,
        birth_date=date(1996, 4, 21),
        country="Ukraine",
        profession="manager",
        telegram_channel="@manager_channel",
    )
    client = Client()
    client.force_login(user)

    response = client.post(f"/api/v1/profiles/drafts/{draft.id}/generate-photo/")

    assert response.status_code == 200
    draft.refresh_from_db()
    assert draft.photo.name
    assert draft.image_source == ProfileDraft.ImageSource.AI


@pytest.mark.django_db
def test_upload_photo_endpoint_rejects_spoofed_image_file():
    user = get_user_model().objects.create_user(email="spoofed-photo@example.com", password="pass")
    account = TelegramAccount.objects.create(owner=user, label="Spoofed Photo", session_name="spoofed-photo")
    draft = ProfileDraft.objects.create(
        owner=user,
        account=account,
        gender=ProfileDraft.Gender.MALE,
        birth_date=date(1993, 4, 21),
        country="Ukraine",
        profession="engineer",
        telegram_channel="@engineer_channel",
    )
    client = Client()
    client.force_login(user)

    response = client.post(
        f"/api/v1/profiles/drafts/{draft.id}/upload-photo/",
        {"photo": SimpleUploadedFile("photo.jpg", b"plain text payload", content_type="image/jpeg")},
    )

    assert response.status_code == 400
    draft.refresh_from_db()
    assert not draft.photo


@pytest.mark.django_db
def test_apply_profile_updates_connected_account(monkeypatch):
    user = get_user_model().objects.create_user(email="apply@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Apply Account",
        session_name="apply-account",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    draft = ProfileDraft.objects.create(
        owner=user,
        account=account,
        gender=ProfileDraft.Gender.OTHER,
        birth_date=date(1995, 4, 21),
        country="Ukraine",
        profession="founder",
        telegram_channel="@founder_channel",
        bio="Building useful tools",
    )
    monkeypatch.setattr("apps.profile_generator.services.run_client_operation", lambda account, operation: True)
    client = Client()
    client.force_login(user)

    response = client.post(f"/api/v1/profiles/drafts/{draft.id}/apply/", data=json.dumps({}), content_type="application/json")

    assert response.status_code == 200
    draft.refresh_from_db()
    assert draft.status == ProfileDraft.Status.APPLIED
    assert AccountHealthEvent.objects.filter(account=account, event_type=AccountHealthEvent.EventType.SUCCESS).exists()


@pytest.mark.django_db
def test_apply_profile_blocks_quarantined_account(monkeypatch):
    user = get_user_model().objects.create_user(email="blocked-profile@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Blocked Account",
        session_name="blocked-profile-account",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.QUARANTINE,
    )
    draft = ProfileDraft.objects.create(
        owner=user,
        account=account,
        gender=ProfileDraft.Gender.MALE,
        birth_date=date(1992, 4, 21),
        country="Ukraine",
        profession="engineer",
        telegram_channel="@engineer_channel",
        bio="Engineer",
    )
    called = SimpleNamespace(value=False)
    monkeypatch.setattr("apps.profile_generator.services.run_client_operation", lambda account, operation: setattr(called, "value", True))
    client = Client()
    client.force_login(user)

    response = client.post(f"/api/v1/profiles/drafts/{draft.id}/apply/")

    assert response.status_code == 200
    draft.refresh_from_db()
    assert draft.status == ProfileDraft.Status.FAILED
    assert called.value is False


@pytest.mark.django_db
def test_delete_profile_draft_endpoint_removes_draft():
    user = get_user_model().objects.create_user(email="delete-profile@example.com", password="pass")
    account = TelegramAccount.objects.create(owner=user, label="Delete Account", session_name="delete-account")
    draft = ProfileDraft.objects.create(
        owner=user,
        account=account,
        gender=ProfileDraft.Gender.FEMALE,
        birth_date=date(1998, 4, 21),
        country="Ukraine",
        profession="designer",
        telegram_channel="@design_channel",
    )
    client = Client()
    client.force_login(user)

    response = client.delete(f"/api/v1/profiles/drafts/{draft.id}/")

    assert response.status_code == 204
    assert not ProfileDraft.objects.filter(id=draft.id).exists()
