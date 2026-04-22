"use client";

import { useEffect } from "react";
import { persistTokensFromUrl } from "@/lib/api";

export default function AuthCallbackPage() {
  useEffect(() => {
    persistTokensFromUrl();
    window.location.replace("/");
  }, []);

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
        <h1>Завершуємо вхід</h1>
        <p>Підключаємо токени доступу і відкриваємо менеджер акаунтів.</p>
      </section>
    </main>
  );
}
