"use client";

import { useEffect, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import { apiFetch, normalizeApiError } from "@/lib/api";

const FACTORS = [
  { key: "age",             label: "Вік",                weight: 18, desc: "Вік акаунта, дата реєстрації, дні активності." },
  { key: "identity",        label: "Ідентичність",        weight: 16, desc: "Fingerprint пристрою, ім'я, преміум, tdata-маркери." },
  { key: "network",         label: "Мережа",              weight: 15, desc: "Сусіди по підмережі, проксі, провенанс IP." },
  { key: "behavior",        label: "Поведінка",           weight: 14, desc: "Дій за весь час, у перші 24 години, заповненість профілю." },
  { key: "block_history",   label: "Історія блокувань",  weight: 13, desc: "Поточний статус та події спамблоку за 30 днів." },
  { key: "recovery_cycles", label: "Цикли відновлення",  weight: 12, desc: "Скільки разів акаунт помирав і повертався в роботу." },
  { key: "origin",          label: "Походження",          weight: 12, desc: "Країна, мова, проксі-гео, патерн завантаження." },
];

const BASE = "/api/v1/accounts/ggr";

function scoreColor(score) {
  if (score === null || score === undefined) return "var(--muted)";
  const n = parseFloat(score);
  if (n >= 7) return "var(--green)";
  if (n >= 4) return "var(--amber)";
  return "var(--red)";
}

function labelBadge(label) {
  if (label === "high") return "green";
  if (label === "medium") return "amber";
  return "red";
}

function labelText(label) {
  if (label === "high") return "Високий";
  if (label === "medium") return "Середній";
  return "Низький";
}

function statusText(s) {
  if (s === "pending") return "В черзі";
  if (s === "running") return "Аналіз…";
  if (s === "done") return "Готово";
  return "Помилка";
}

function ScoreBar({ score }) {
  const pct = score ? Math.round((parseFloat(score) / 10) * 100) : 0;
  return (
    <div style={{ height: 6, borderRadius: 4, background: "rgba(255,255,255,0.08)", overflow: "hidden", marginTop: 6 }}>
      <div style={{ width: `${pct}%`, height: "100%", borderRadius: 4, background: scoreColor(score), transition: "width 0.4s" }} />
    </div>
  );
}

function AccountCard({ account, ggr, onCheck, onCancel }) {
  const checking = ggr && (ggr.status === "pending" || ggr.status === "running");
  return (
    <div style={{
      border: "1px solid var(--line)", borderRadius: 14, padding: "16px 18px",
      background: "rgba(255,255,255,0.03)", display: "flex", flexDirection: "column", gap: 10,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 14 }}>{account.label}</div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
            {account.phone_number || account.telegram_username || `#${account.id}`}
          </div>
        </div>
        {ggr && ggr.status === "done" ? (
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 26, fontWeight: 800, color: scoreColor(ggr.score), lineHeight: 1 }}>
              {parseFloat(ggr.score).toFixed(1)}
            </div>
            <div style={{ fontSize: 10, color: "var(--muted)" }}>/ 10</div>
          </div>
        ) : checking ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
            <span style={{ fontSize: 12, color: "var(--amber)" }}>⏳ {statusText(ggr.status)}</span>
            <button
              type="button"
              className="ghost-button"
              style={{ fontSize: 11, padding: "2px 8px", color: "var(--red)" }}
              onClick={() => onCancel([account.id])}
            >✕ Скасувати</button>
          </div>
        ) : (
          <span style={{ fontSize: 12, color: "var(--muted)" }}>не перевірено</span>
        )}
      </div>

      {ggr && ggr.status === "done" && (
        <>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <span className={`badge ${labelBadge(ggr.label)}`}>{labelText(ggr.label)}</span>
            {ggr.geo && <span className="badge gray">{ggr.geo}</span>}
            {ggr.recommendations?.warmup_needed && <span className="badge amber">Потрібен прогрів</span>}
          </div>
          <ScoreBar score={ggr.score} />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginTop: 4 }}>
            <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: "8px 10px", textAlign: "center" }}>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>7 днів</div>
              <div style={{ fontSize: 15, fontWeight: 700, color: (ggr.survival_7d >= 70 ? "var(--green)" : ggr.survival_7d >= 50 ? "var(--amber)" : "var(--red)") }}>
                {ggr.survival_7d}%
              </div>
            </div>
            <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: "8px 10px", textAlign: "center" }}>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>30 днів</div>
              <div style={{ fontSize: 15, fontWeight: 700, color: (ggr.survival_30d >= 60 ? "var(--green)" : ggr.survival_30d >= 40 ? "var(--amber)" : "var(--red)") }}>
                {ggr.survival_30d}%
              </div>
            </div>
            <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: "8px 10px", textAlign: "center" }}>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>Строк</div>
              <div style={{ fontSize: 15, fontWeight: 700 }}>{ggr.median_lifetime_days}д</div>
            </div>
          </div>
          {ggr.recommendations?.safe_modules?.length > 0 && (
            <div style={{ fontSize: 12 }}>
              <span style={{ color: "var(--green)" }}>✓ </span>
              {ggr.recommendations.safe_modules.join(", ")}
            </div>
          )}
          {ggr.recommendations?.caution_modules?.length > 0 && (
            <div style={{ fontSize: 12 }}>
              <span style={{ color: "var(--amber)" }}>⚠ </span>
              {ggr.recommendations.caution_modules.join(", ")}
            </div>
          )}
          {ggr.analysis && (
            <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>{ggr.analysis}</div>
          )}
        </>
      )}

      {ggr?.status === "failed" && (
        <div style={{ fontSize: 12, color: "var(--red)" }}>⚠ {ggr.error}</div>
      )}

      {!checking && (
        <button
          type="button"
          className="ghost-button"
          style={{ fontSize: 12, marginTop: 4 }}
          onClick={() => onCheck([account.id])}
        >
          {ggr?.status === "done" ? "↻ Перевірити знову" : "▷ Перевірити GGR"}
        </button>
      )}
    </div>
  );
}

function DetailModal({ ggr, account, onClose }) {
  const [expandedFactor, setExpandedFactor] = useState(null);
  if (!ggr || ggr.status !== "done") return null;
  const factors = ggr.factors || {};
  const rec = ggr.recommendations || {};

  return (
    <div
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}
      onClick={onClose}
    >
      <div
        style={{ background: "var(--panel-strong)", border: "1px solid var(--line)", borderRadius: 20, padding: 28, maxWidth: 560, width: "100%", maxHeight: "90vh", overflowY: "auto", boxShadow: "var(--shadow)" }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
          <div>
            <div className="eyebrow">GGR · Детальний аналіз</div>
            <h3 style={{ margin: "4px 0 0" }}>{account?.label}</h3>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 36, fontWeight: 900, color: scoreColor(ggr.score), lineHeight: 1 }}>{parseFloat(ggr.score).toFixed(1)}</div>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>/ 10 · {labelText(ggr.label).toUpperCase()}</div>
          </div>
        </div>

        {/* Survival stats */}
        <div className="warmup-grid two" style={{ marginBottom: 20 }}>
          <div className="dashed-panel" style={{ textAlign: "center" }}>
            <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Потенціал</div>
            <div style={{ fontSize: 28, fontWeight: 800, color: scoreColor(ggr.potential) }}>{parseFloat(ggr.potential).toFixed(1)}</div>
          </div>
          <div className="dashed-panel" style={{ textAlign: "center" }}>
            <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Строк життя</div>
            <div style={{ fontSize: 28, fontWeight: 800 }}>~{ggr.median_lifetime_days}д</div>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 20 }}>
          <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 10, padding: 14, textAlign: "center" }}>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>Виживе 7 днів</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: ggr.survival_7d >= 70 ? "var(--green)" : ggr.survival_7d >= 50 ? "var(--amber)" : "var(--red)" }}>{ggr.survival_7d}%</div>
            <div style={{ fontSize: 10, color: "var(--muted)" }}>з {ggr.similar_count || "N"} схожих акаунтів</div>
          </div>
          <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 10, padding: 14, textAlign: "center" }}>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>Виживе 30 днів</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: ggr.survival_30d >= 60 ? "var(--green)" : ggr.survival_30d >= 40 ? "var(--amber)" : "var(--red)" }}>{ggr.survival_30d}%</div>
            <div style={{ fontSize: 10, color: "var(--muted)" }}>{ggr.similar_params || ""}</div>
          </div>
        </div>

        {/* Factors — 7-factor breakdown */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", color: "var(--muted)", textTransform: "uppercase" }}>ДЕТАЛІ ОЦІНКИ</span>
            <span style={{ background: "rgba(255,255,255,0.12)", borderRadius: 10, padding: "1px 7px", fontSize: 11, fontWeight: 700 }}>{FACTORS.length}</span>
          </div>
          {FACTORS.map((f) => {
            const raw = factors[f.key];
            const score = raw == null ? null : typeof raw === "object" ? raw.score : raw;
            const details = typeof raw === "object" ? (raw.details || []) : [];
            const isExpanded = expandedFactor === f.key;
            const pct = score != null ? Math.round((parseFloat(score) / 10) * 100) : 0;
            const dotColor = score == null ? "var(--muted)" : scoreColor(score);

            return (
              <div key={f.key} style={{ borderBottom: "1px solid var(--line)", paddingBottom: 12, marginBottom: 12 }}>
                <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                  {/* Status dot */}
                  <div style={{ width: 8, height: 8, borderRadius: "50%", background: dotColor, marginTop: 6, flexShrink: 0 }} />

                  {/* Name + desc */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
                      <span style={{ fontWeight: 700, fontSize: 13 }}>{f.label}</span>
                      <span style={{ background: "rgba(255,255,255,0.1)", borderRadius: 8, padding: "1px 6px", fontSize: 10, fontWeight: 600, color: "var(--muted)" }}>{f.weight}%</span>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.4 }}>{f.desc}</div>
                  </div>

                  {/* Score + bar + expand */}
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                    {/* Progress bar */}
                    <div style={{ width: 72, height: 5, borderRadius: 3, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                      <div style={{ width: `${pct}%`, height: "100%", background: dotColor, borderRadius: 3, transition: "width 0.4s" }} />
                    </div>

                    {/* Score badge */}
                    {score != null ? (
                      <span style={{ fontSize: 13, fontWeight: 800, color: scoreColor(score), minWidth: 28, textAlign: "right" }}>
                        {parseFloat(score).toFixed(1)}
                      </span>
                    ) : (
                      <span style={{ fontSize: 11, color: "var(--muted)", minWidth: 28, textAlign: "right" }}>—</span>
                    )}

                    {/* Expand toggle */}
                    <button
                      type="button"
                      onClick={() => setExpandedFactor(isExpanded ? null : f.key)}
                      style={{ background: "none", border: "none", cursor: details.length > 0 ? "pointer" : "default", color: details.length > 0 ? "var(--text)" : "var(--muted)", fontSize: 11, padding: "2px 4px", opacity: details.length > 0 ? 1 : 0.4, whiteSpace: "nowrap" }}
                    >
                      {isExpanded ? "▾ Деталі" : "▸ Деталі"}
                    </button>
                  </div>
                </div>

                {/* Expanded details */}
                {isExpanded && details.length > 0 && (
                  <div style={{ marginLeft: 18, marginTop: 8, padding: "8px 12px", background: "rgba(255,255,255,0.03)", borderRadius: 8, borderLeft: `2px solid ${dotColor}` }}>
                    {details.map((d, i) => (
                      <div key={i} style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.6, display: "flex", gap: 6 }}>
                        <span style={{ color: dotColor, flexShrink: 0 }}>•</span>
                        <span>{d}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Recommendations */}
        <div className="dashed-panel" style={{ marginBottom: 20 }}>
          <div className="section-title" style={{ marginBottom: 12 }}>
            <span className="section-icon green">✓</span>
            <h4 style={{ margin: 0 }}>Що робити зараз</h4>
          </div>
          {rec.warmup_needed && (
            <div style={{ marginBottom: 8, fontSize: 13 }}>
              <span style={{ color: "var(--amber)" }}>⚠ </span>
              Рекомендується прогрів перед запуском модулів
            </div>
          )}
          {rec.safe_modules?.length > 0 && (
            <div style={{ marginBottom: 6, fontSize: 13 }}>
              <span style={{ color: "var(--green)" }}>✓ Підходить: </span>
              {rec.safe_modules.join(", ")}
            </div>
          )}
          {rec.caution_modules?.length > 0 && (
            <div style={{ marginBottom: 6, fontSize: 13 }}>
              <span style={{ color: "var(--amber)" }}>! З обережністю: </span>
              {rec.caution_modules.join(", ")}
            </div>
          )}
          {rec.avoid?.length > 0 && (
            <div style={{ marginBottom: 6, fontSize: 13 }}>
              <span style={{ color: "var(--red)" }}>✕ Уникати: </span>
              {rec.avoid.join(", ")}
            </div>
          )}
          {rec.next_check_days && (
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
              Наступна перевірка: через {rec.next_check_days} днів
            </div>
          )}
        </div>

        {ggr.analysis && (
          <div style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.6, marginBottom: 16 }}>{ggr.analysis}</div>
        )}

        <button type="button" className="ghost-button" style={{ width: "100%" }} onClick={onClose}>Закрити</button>
      </div>
    </div>
  );
}

export default function GGRPage() {
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [detail, setDetail] = useState(null);
  const pollRef = useRef(null);

  const load = async () => {
    try {
      const data = await apiFetch(`${BASE}/overview/`);
      setOverview(data);
      setError("");
    } catch (e) {
      setError(normalizeApiError(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    pollRef.current = setInterval(load, 5000);
    return () => clearInterval(pollRef.current);
  }, []);

  const handleCheck = async (ids) => {
    setChecking(true);
    try {
      await apiFetch(`${BASE}/check/`, { method: "POST", body: { account_ids: ids } });
      await load();
    } catch (e) {
      alert(normalizeApiError(e));
    } finally {
      setChecking(false);
    }
  };

  const handleCancel = async (ids) => {
    try {
      await apiFetch(`${BASE}/cancel/`, { method: "POST", body: { account_ids: ids } });
      await load();
    } catch (e) {
      alert(normalizeApiError(e));
    }
  };

  const handleCheckAll = () => handleCheck((overview?.accounts || []).map(a => a.id));
  const handleCheckSelected = () => handleCheck([...selected]);

  const toggleSelect = (id) => setSelected(prev => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  const accounts = overview?.accounts || [];
  const geoData = overview?.geo_benchmark || [];

  const pendingCount = accounts.filter(a => a.ggr && (a.ggr.status === "pending" || a.ggr.status === "running")).length;
  const doneCount = accounts.filter(a => a.ggr?.status === "done").length;

  const openDetail = (account) => {
    if (account.ggr?.status === "done") setDetail({ ggr: account.ggr, account });
  };

  if (loading && !overview) return (
    <AppShell>
      <div style={{ padding: 40, color: "var(--muted)" }}>Завантаження…</div>
    </AppShell>
  );

  return (
    <AppShell>
      {/* Hero */}
      <section className="warmup-card hero-card">
        <div>
          <div className="eyebrow">analytics</div>
          <h2>GGR · Рейтинг акаунтів</h2>
          <p>AI аналізує параметри акаунта і прогнозує його виживаність під автоматизацією.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="ghost-button" onClick={load}>Оновити</button>
          <button className="primary-button" disabled={checking || !accounts.length} onClick={handleCheckAll}>
            {checking ? "Аналіз…" : `▷ Перевірити всі (${accounts.length})`}
          </button>
        </div>
      </section>

      {error && <div className="alert error">{error}</div>}

      {/* Stats */}
      <section className="warmup-card">
        <div className="launch-stats">
          <div><span>Акаунтів</span><b>{accounts.length}</b></div>
          <div><span>Перевірено</span><b>{doneCount}</b></div>
          <div><span>В аналізі</span><b>{pendingCount}</b></div>
          <div>
            <span>Середній GGR</span>
            <b style={{ color: scoreColor(doneCount ? (accounts.filter(a => a.ggr?.status === "done").reduce((s, a) => s + parseFloat(a.ggr.score), 0) / doneCount).toFixed(1) : null) }}>
              {doneCount ? (accounts.filter(a => a.ggr?.status === "done").reduce((s, a) => s + parseFloat(a.ggr.score), 0) / doneCount).toFixed(1) : "—"}
            </b>
          </div>
        </div>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 24 }}>
        {/* Accounts grid */}
        <div>
          {selected.size > 0 && (
            <div style={{ display: "flex", gap: 10, marginBottom: 12, alignItems: "center" }}>
              <span style={{ fontSize: 13, color: "var(--muted)" }}>Вибрано: {selected.size}</span>
              <button type="button" className="ghost-button" style={{ fontSize: 12 }} onClick={handleCheckSelected}>
                ▷ Перевірити вибрані
              </button>
              <button type="button" className="ghost-button" style={{ fontSize: 12 }} onClick={() => setSelected(new Set())}>
                Скинути
              </button>
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 14 }}>
            {accounts.map(account => (
              <div key={account.id} style={{ position: "relative" }}>
                <input
                  type="checkbox"
                  checked={selected.has(account.id)}
                  onChange={() => toggleSelect(account.id)}
                  style={{ position: "absolute", top: 12, right: 12, zIndex: 1, width: 16, height: 16 }}
                />
                <div onClick={() => openDetail(account)} style={{ cursor: account.ggr?.status === "done" ? "pointer" : "default" }}>
                  <AccountCard
                    account={account}
                    ggr={account.ggr}
                    onCheck={handleCheck}
                    onCancel={handleCancel}
                  />
                </div>
              </div>
            ))}
            {accounts.length === 0 && (
              <div style={{ gridColumn: "1/-1", textAlign: "center", padding: 40, color: "var(--muted)" }}>
                Немає підключених акаунтів
              </div>
            )}
          </div>
        </div>

        {/* Geo benchmark */}
        <div>
          <section className="warmup-card" style={{ position: "sticky", top: 20 }}>
            <div className="section-title" style={{ marginBottom: 16 }}>
              <span className="section-icon blue">⬡</span>
              <div><h3>Бенчмарк по гео</h3><p>Середній GGR та виживаність по країнах</p></div>
            </div>

            {geoData.length === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: 13, textAlign: "center", padding: 20 }}>
                Перевірте акаунти щоб побачити статистику
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {geoData.map(row => (
                  <div key={row.geo} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ width: 28, fontSize: 13, fontWeight: 700, color: "var(--text)" }}>{row.geo}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ height: 6, borderRadius: 3, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                        <div style={{ width: `${Math.round((parseFloat(row.avg_score) / 10) * 100)}%`, height: "100%", background: scoreColor(row.avg_score), borderRadius: 3 }} />
                      </div>
                    </div>
                    <span style={{ fontSize: 13, fontWeight: 700, color: scoreColor(row.avg_score), minWidth: 30 }}>
                      {parseFloat(row.avg_score).toFixed(1)}
                    </span>
                    <span style={{ fontSize: 11, color: "var(--muted)", minWidth: 28 }}>{row.count}шт</span>
                  </div>
                ))}
              </div>
            )}

            {/* Scale legend */}
            <div style={{ marginTop: 20, borderTop: "1px solid var(--line)", paddingTop: 14 }}>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 8 }}>Шкала 1.0 — 10.0</div>
              <div style={{ display: "flex", gap: 6 }}>
                <span style={{ fontSize: 11, color: "var(--green)" }}>● 7+ Високий</span>
                <span style={{ fontSize: 11, color: "var(--amber)" }}>● 4-7 Середній</span>
                <span style={{ fontSize: 11, color: "var(--red)" }}>● &lt;4 Низький</span>
              </div>
            </div>
          </section>
        </div>
      </div>

      {/* Detail modal */}
      {detail && (
        <DetailModal ggr={detail.ggr} account={detail.account} onClose={() => setDetail(null)} />
      )}
    </AppShell>
  );
}
