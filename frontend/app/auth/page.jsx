"use client";

import { useEffect, useState } from "react";
import { apiFetch, normalizeApiError, persistTokensFromUrl, saveAuthTokens } from "@/lib/api";

export default function AuthPage() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [telegramBot, setTelegramBot] = useState("");

  useEffect(() => {
    if (persistTokensFromUrl()) {
      window.location.href = "/";
    }
  }, []);

  useEffect(() => {
    apiFetch("/api/v1/auth/config/")
      .then((config) => setTelegramBot(config.telegram_bot_username || process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME || ""))
      .catch(() => setTelegramBot(process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME || ""));
  }, []);

  useEffect(() => {
    window.handleTelegramAuth = async function handleTelegramAuth(user) {
      setError("");
      setBusy(true);
      try {
        const payload = await apiFetch("/api/v1/auth/telegram/", {
          method: "POST",
          body: user,
        });
        saveAuthTokens(payload.tokens);
        window.location.href = "/";
      } catch (exc) {
        setError(normalizeApiError(exc));
        setBusy(false);
      }
    };

    return () => {
      delete window.handleTelegramAuth;
    };
  }, []);

  useEffect(() => {
    if (!telegramBot || document.getElementById("telegram-login-widget")) return;
    const container = document.getElementById("telegram-login-container");
    if (!container) return;
    const script = document.createElement("script");
    script.id = "telegram-login-widget";
    script.async = true;
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.setAttribute("data-telegram-login", telegramBot);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-userpic", "false");
    script.setAttribute("data-request-access", "write");
    script.setAttribute("data-onauth", "window.handleTelegramAuth(user)");
    container.appendChild(script);
  }, [telegramBot]);

  async function googleLogin() {
    setError("");
    setBusy(true);
    try {
      const origin = window.location.origin;
      const backend = (process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
      const params = new URLSearchParams({
        redirect_uri: `${backend}/api/v1/auth/google/callback/`,
        next: `${origin}/auth/callback`,
      });
      const payload = await apiFetch(`/api/v1/auth/google/login/?${params.toString()}`);
      window.location.href = payload.url;
    } catch (exc) {
      setError(normalizeApiError(exc));
      setBusy(false);
    }
  }

  return (
    <main className="auth-screen">
      <section className="auth-card">
        <div className="brand auth-brand">
          <div className="brand-mark">S</div>
          <div>
            <div className="brand-title">StogramGPT</div>
            <div className="brand-plan">secure login</div>
          </div>
        </div>
        <h1>Вхід у комбайн</h1>
        <p>Увійдіть через Google або Telegram. Після входу відкриється менеджер акаунтів.</p>
        {error && <div className="alert error">{error}</div>}
        <div className="sso-stack next-auth-stack">
          <div id="telegram-login-container" className="telegram-login-wrap">
            {!telegramBot && <div className="button-disabled">Telegram Login ще не налаштовано</div>}
          </div>
        </div>
        <div className="auth-divider"><span>або</span></div>
        <button className="primary-button auth-button" type="button" onClick={googleLogin} disabled={busy}>
          {busy ? "Відкриваю Google..." : "Увійти через Google"}
        </button>
      </section>
    </main>
  );
}
