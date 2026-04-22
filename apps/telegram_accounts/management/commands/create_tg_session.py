from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from pyrogram import Client


class Command(BaseCommand):
    help = "Create or verify an interactive Pyrogram .session file for Telegram user accounts."

    def add_arguments(self, parser):
        parser.add_argument("name", help="Session name without .session extension.")
        parser.add_argument(
            "--workdir",
            default="tg-session",
            help="Directory where Pyrogram will create the .session file.",
        )

    def handle(self, *args, **options):
        if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
            raise CommandError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be configured.")

        name = options["name"]
        workdir = Path(options["workdir"]).expanduser().resolve()
        workdir.mkdir(parents=True, exist_ok=True)

        app = Client(
            name,
            api_id=settings.TELEGRAM_API_ID,
            api_hash=settings.TELEGRAM_API_HASH,
            workdir=workdir,
        )

        self.stdout.write(
            "Pyrogram will ask for phone, code and 2FA password if this session is not authorized yet."
        )
        app.start()
        try:
            me = app.get_me()
            session_path = workdir / f"{name}.session"
            self.stdout.write(
                self.style.SUCCESS(
                    f"Authorized as {me.id} @{me.username or '-'} {me.first_name or ''}".strip()
                )
            )
            self.stdout.write(self.style.SUCCESS(f"Session file: {session_path}"))
        finally:
            app.stop()
