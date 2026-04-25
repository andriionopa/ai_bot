"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { apiFetch, clearAuthTokens } from "@/lib/api";

const mainNav = [
  { href: "/", icon: "▦", label: "Менеджер акаунтів" },
  { href: "/warmup", icon: "♨", label: "Прогрів акаунтів" },
];

const parserItems = [
  { href: "/parser/channels", label: "Парсер каналів" },
  { href: "/parser/messages", label: "Парсер по повідомленнях" },
  { href: "/parser/comments", label: "Парсер коментарів" },
  { href: "/parser/history",  label: "Історія парсингу" },
];

const PAGE_TITLE = {
  "/parser/channels": "Парсер каналів",
  "/parser/messages": "Парсер по повідомленнях",
  "/parser/comments": "Парсер коментарів",
  "/parser/history":  "Історія парсингу",
  "/warmup":          "Прогрів акаунтів",
};

export default function AppShell({ children, userLabel }) {
  const pathname = usePathname();
  const onParser = pathname.startsWith("/parser");
  const [parserOpen, setParserOpen] = useState(onParser);

  async function logout() {
    try {
      await apiFetch("/api/v1/auth/logout/", { method: "POST", body: {} });
    } catch {}
    clearAuthTokens();
    window.location.href = "/auth";
  }

  const pageTitle = PAGE_TITLE[pathname] ?? (onParser ? "Парсинг даних" : "Менеджер акаунтів");

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">S</div>
          <div>
            <div className="brand-title">StogramGPT</div>
            <div className="brand-plan">повна</div>
          </div>
        </div>

        <div className="nav-section">Головна</div>
        <nav className="nav-list">
          {mainNav.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link key={item.href} href={item.href} className={`nav-item ${active ? "active" : ""}`}>
                <span className="nav-icon">{item.icon}</span>
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="nav-section">Модулі</div>
        <div className="nav-item disabled"><span className="nav-icon">✎</span>Нейрокоментинг</div>
        <div className="nav-item disabled"><span className="nav-icon">◌</span>Масові реакції</div>

        {/* Парсинг даних — collapsible group */}
        <button
          type="button"
          className={`nav-group-header ${onParser ? "active" : ""} ${parserOpen ? "open" : ""}`}
          onClick={() => setParserOpen((prev) => !prev)}
        >
          <span className="nav-icon">◈</span>
          <span>Парсинг даних</span>
          <span className="nav-chevron">{parserOpen ? "∧" : "∨"}</span>
        </button>

        {parserOpen && (
          <div className="nav-sub-list">
            {parserItems.map((item, idx) =>
              item.disabled || !item.href ? (
                <span key={idx} className="nav-sub-item disabled">{item.label}</span>
              ) : (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`nav-sub-item ${pathname === item.href ? "active" : ""}`}
                >
                  {item.label}
                </Link>
              )
            )}
          </div>
        )}
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">workspace</div>
            <h1>{pageTitle}</h1>
          </div>
          <div className="topbar-actions">
            <span className="user-pill">{userLabel || "operator"}</span>
            <button className="ghost-button" type="button" onClick={logout}>Logout</button>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
