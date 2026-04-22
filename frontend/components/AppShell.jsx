"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { apiFetch, clearAuthTokens } from "@/lib/api";

const nav = [
  { href: "/", icon: "▦", label: "Менеджер акаунтів" },
  { href: "/warmup", icon: "♨", label: "Прогрів акаунтів" },
];

export default function AppShell({ children, userLabel }) {
  const pathname = usePathname();

  async function logout() {
    try {
      await apiFetch("/api/v1/auth/logout/", { method: "POST", body: {} });
    } catch {
      // Even if the server session is already gone, return to login.
    }
    clearAuthTokens();
    window.location.href = "/auth";
  }

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
          {nav.map((item) => {
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
        <div className="nav-item disabled"><span className="nav-icon">▣</span>Парсинг даних</div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">workspace</div>
            <h1>{pathname === "/warmup" ? "Прогрів акаунтів" : "Менеджер акаунтів"}</h1>
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
