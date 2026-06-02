"use client";

import { useEffect, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import { apiFetch, normalizeApiError } from "@/lib/api";

const BASE = "/api/v1/neuro-commenting";

const defaultForm = {
  name: "Нейрокоментинг #1",
  sources: [],
  use_ai_prompt: true,
  selected_prompts: [],
  comment_mode: "all",
  keywords: [],
  random_probability: 0.5,
  work_mode: "monitoring",
  max_comments: 0,
  duration_minutes: 60,
  language_mode: "auto",
  language: "ru",
  write_as_channel: false,
  write_as_channel_username: "",
  auto_reply_enabled: false,
  auto_reply_message: "",
  first_message_strategy: false,
  first_message_text: "👍",
  first_message_edit_delay: 45,
  account_rotation: true,
  rotation_every_n: 5,
  comment_delay_min: 53,
  comment_delay_max: 99,
  entry_delay_min: 84,
  entry_delay_max: 156,
  ai_protection: true,
  protection_mode: "balanced",
};

function Toggle({ checked, onChange, label, note }) {
  return (
    <label className="toggle-line" style={{ fontWeight: 400 }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="switch" />
      <span>
        {label && <b style={{ fontWeight: 600 }}>{label}</b>}
        {note && <small style={{ display: "block", color: "var(--muted)", fontWeight: 400, fontSize: 12, marginTop: 2 }}>{note}</small>}
      </span>
    </label>
  );
}

function PromptCard({ prompt, selected, onSelect, onPreview }) {
  return (
    <button
      type="button"
      className={selected ? "active" : ""}
      style={{
        border: selected ? "2px solid var(--blue)" : "1px solid var(--line)",
        borderRadius: 10, padding: "10px 12px", cursor: "pointer", position: "relative",
        background: selected ? "rgba(27,164,255,0.12)" : "rgba(255,255,255,0.03)",
        minWidth: 130, maxWidth: 170, textAlign: "left",
        display: "flex", flexDirection: "column", gap: 6,
      }}
      onClick={onSelect}
    >
      {selected && (
        <div style={{
          position: "absolute", top: -8, right: -8, width: 20, height: 20,
          borderRadius: "50%", background: "var(--blue)", color: "#fff",
          display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11,
        }}>✓</div>
      )}
      <span style={{ fontWeight: 600, fontSize: 13 }}>{prompt.name}</span>
      <div style={{ display: "flex", gap: 6 }}>
        <button type="button" className="ghost-button" style={{ fontSize: 11, padding: "2px 8px" }}
          onClick={(e) => { e.stopPropagation(); onPreview(prompt); }}>👁</button>
      </div>
    </button>
  );
}

function formatDate(v) {
  if (!v) return "—";
  return new Date(v).toLocaleString("uk-UA", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function statusLabel(s) {
  if (s === "running") return "В роботі";
  if (s === "succeeded") return "Завершено";
  if (s === "failed") return "Помилка";
  if (s === "stopped") return "Зупинено";
  return "Чернетка";
}

function statusBadge(s) {
  if (s === "running") return "blue";
  if (s === "succeeded") return "green";
  if (s === "failed") return "red";
  if (s === "stopped") return "amber";
  return "gray";
}

function levelClass(l) {
  if (l === "success") return "success";
  if (l === "error") return "error";
  if (l === "warning") return "warning";
  return "";
}

export default function NeuroCommentingPage() {
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [form, setForm] = useState(defaultForm);
  const [editingJob, setEditingJob] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [logFilter, setLogFilter] = useState("all");
  const [sourcesText, setSourcesText] = useState("");
  const [keywordsText, setKeywordsText] = useState("");
  const [previewPrompt, setPreviewPrompt] = useState(null);
  const [newPromptName, setNewPromptName] = useState("");
  const [newPromptText, setNewPromptText] = useState("");
  const [creatingPrompt, setCreatingPrompt] = useState(false);
  const [blacklistFilter, setBlacklistFilter] = useState("all");
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
    pollRef.current = setInterval(load, 4000);
    return () => clearInterval(pollRef.current);
  }, []);

  const setField = (key, val) => setForm(prev => ({ ...prev, [key]: val }));

  const parseSources = () => sourcesText.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);
  const parseKeywords = () => keywordsText.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);

  const startEdit = (job) => {
    setEditingJob(job);
    setForm({
      name: job.name,
      sources: job.sources || [],
      use_ai_prompt: job.use_ai_prompt,
      selected_prompts: job.selected_prompts || [],
      comment_mode: job.comment_mode,
      keywords: job.keywords || [],
      random_probability: job.random_probability,
      work_mode: job.work_mode,
      max_comments: job.max_comments,
      duration_minutes: job.duration_minutes,
      language_mode: job.language_mode,
      language: job.language,
      write_as_channel: job.write_as_channel,
      write_as_channel_username: job.write_as_channel_username || "",
      auto_reply_enabled: job.auto_reply_enabled,
      auto_reply_message: job.auto_reply_message || "",
      first_message_strategy: job.first_message_strategy,
      first_message_text: job.first_message_text || "👍",
      first_message_edit_delay: job.first_message_edit_delay,
      account_rotation: job.account_rotation,
      rotation_every_n: job.rotation_every_n,
      comment_delay_min: job.comment_delay_min,
      comment_delay_max: job.comment_delay_max,
      entry_delay_min: job.entry_delay_min,
      entry_delay_max: job.entry_delay_max,
      ai_protection: job.ai_protection,
      protection_mode: job.protection_mode || "balanced",
      accounts: job.accounts || [],
    });
    setSourcesText((job.sources || []).join("\n"));
    setKeywordsText((job.keywords || []).join("\n"));
  };

  const cancelEdit = () => {
    setEditingJob(null);
    setForm(defaultForm);
    setSourcesText("");
    setKeywordsText("");
    setSaveError("");
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveError("");
    const payload = { ...form, sources: parseSources(), keywords: parseKeywords(), accounts: form.accounts || [] };
    try {
      if (editingJob) {
        await apiFetch(`${BASE}/jobs/${editingJob.id}/`, { method: "PATCH", body: payload });
      } else {
        await apiFetch(`${BASE}/jobs/`, { method: "POST", body: payload });
      }
      cancelEdit();
      await load();
    } catch (e) {
      setSaveError(normalizeApiError(e));
    } finally {
      setSaving(false);
    }
  };

  const handleStart = async (job) => {
    try { await apiFetch(`${BASE}/jobs/${job.id}/start/`, { method: "POST" }); await load(); } catch (e) { alert(normalizeApiError(e)); }
  };
  const handleStop = async (job) => {
    try { await apiFetch(`${BASE}/jobs/${job.id}/stop/`, { method: "POST" }); await load(); } catch (e) { alert(normalizeApiError(e)); }
  };
  const handleDelete = async (job) => {
    if (!confirm(`Видалити задачу «${job.name}»?`)) return;
    try { await apiFetch(`${BASE}/jobs/${job.id}/`, { method: "DELETE" }); await load(); } catch (e) { alert(normalizeApiError(e)); }
  };
  const clearFinished = async () => {
    try { await apiFetch(`${BASE}/jobs/clear_finished/`, { method: "DELETE" }); await load(); } catch (e) { alert(normalizeApiError(e)); }
  };

  const handleCreatePrompt = async () => {
    if (!newPromptName.trim() || !newPromptText.trim()) return;
    setCreatingPrompt(true);
    try {
      await apiFetch(`${BASE}/prompts/`, { method: "POST", body: { name: newPromptName.trim(), text: newPromptText.trim() } });
      setNewPromptName("");
      setNewPromptText("");
      await load();
    } catch (e) { alert(normalizeApiError(e)); } finally { setCreatingPrompt(false); }
  };

  const handleDeletePrompt = async (p) => {
    if (p.is_system || !confirm(`Видалити промпт «${p.name}»?`)) return;
    try { await apiFetch(`${BASE}/prompts/${p.id}/`, { method: "DELETE" }); await load(); } catch (e) { alert(normalizeApiError(e)); }
  };

  const handleDeleteBlacklist = async (item) => {
    try { await apiFetch(`${BASE}/blacklist/${item.id}/`, { method: "DELETE" }); await load(); } catch (e) { alert(normalizeApiError(e)); }
  };
  const clearBlacklist = async () => {
    if (!confirm("Очистити весь чорний список?")) return;
    try { await apiFetch(`${BASE}/blacklist/clear_all/`, { method: "DELETE" }); await load(); } catch (e) { alert(normalizeApiError(e)); }
  };

  const logs = overview?.logs || [];
  const filteredLogs = logFilter === "all" ? logs : logs.filter(l => l.level === logFilter);

  const selectedPromptIds = new Set(form.selected_prompts || []);
  const togglePrompt = (id) => {
    if (selectedPromptIds.has(id)) setField("selected_prompts", [...selectedPromptIds].filter(x => x !== id));
    else setField("selected_prompts", [...selectedPromptIds, id]);
  };

  const blacklist = overview?.blacklist || [];
  const filteredBlacklist = blacklistFilter === "all" ? blacklist : blacklist.filter(b => b.account_label === blacklistFilter);
  const blacklistAccounts = [...new Set(blacklist.map(b => b.account_label).filter(Boolean))];

  const allAccounts = overview?.accounts || [];
  const selectedAccountIds = new Set(form.accounts || []);
  const toggleAccount = (id) => {
    if (selectedAccountIds.has(id)) setField("accounts", [...selectedAccountIds].filter(x => x !== id));
    else setField("accounts", [...selectedAccountIds, id]);
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
          <div className="eyebrow">ai automation</div>
          <h2>Нейрокоментинг</h2>
          <p>Автоматичне коментування постів у Telegram-каналах за допомогою ШІ.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <a href="#" className="ghost-button" style={{ fontSize: 12 }}>ℹ О модулі</a>
          <button className="ghost-button" onClick={load}>Оновити</button>
        </div>
      </section>

      {error && <div className="alert error">{error}</div>}

      {/* Accounts */}
      <section className="warmup-card">
        <div className="section-title">
          <span className="section-icon blue">👥</span>
          <div><h3>Вибір акаунтів</h3><p>Акаунти, від імені яких писатимуться коментарі</p></div>
          <strong className="badge blue" style={{ marginLeft: "auto" }}>{selectedAccountIds.size} вибрано</strong>
        </div>
        <div className="account-picker">
          {allAccounts.map(a => (
            <button
              key={a.id}
              className={selectedAccountIds.has(a.id) ? "active" : ""}
              onClick={() => toggleAccount(a.id)}
            >
              <b>{a.label}</b>
              <span>{a.phone_number}</span>
            </button>
          ))}
          {allAccounts.length === 0 && <div className="empty-state">Немає підключених акаунтів</div>}
        </div>
      </section>

      {/* Target channels */}
      <section className="warmup-card pink-soft">
        <div className="section-title">
          <span className="section-icon violet">#</span>
          <div><h3>Цільові канали</h3><p>Канали, у яких бот коментуватиме пости</p></div>
          <strong className="badge" style={{ marginLeft: "auto" }}>{parseSources().length} каналів</strong>
        </div>
        <textarea
          className="large-textarea"
          value={sourcesText}
          onChange={e => setSourcesText(e.target.value)}
          placeholder={"@channel1\nhttps://t.me/channel2\nhttps://t.me/addlist/AbCdEfGh"}
          rows={5}
        />
        <p style={{ marginTop: 10, fontSize: 12, color: "var(--muted)", lineHeight: 1.6 }}>
          Папку Telegram (t.me/addlist/…) безпечніше додавати замість 50 окремих каналів — це один join-виклик замість десятків, що різко знижує ризик flood-wait.
          Для приватних каналів додавайте 5–15 на день.
        </p>
      </section>

      {/* Message settings */}
      <section className="warmup-card">
        <div className="section-title">
          <span className="section-icon pink">✦</span>
          <div><h3>Налаштування повідомлень</h3><p>AI промпти та мова генерації коментарів</p></div>
        </div>

        <Toggle
          checked={form.use_ai_prompt}
          onChange={v => setField("use_ai_prompt", v)}
          label="Використовувати AI промпт"
          note="ШІ генерує коментар на основі тексту поста"
        />

        {form.use_ai_prompt && (
          <div style={{ marginTop: 20 }}>
            <div className="warmup-grid two">
              <div className="dashed-panel">
                <h4 style={{ margin: "0 0 12px" }}>Системні промпти ({(overview?.system_prompts || []).length})</h4>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  {(overview?.system_prompts || []).map(p => (
                    <PromptCard key={p.id} prompt={p}
                      selected={selectedPromptIds.has(p.id)}
                      onSelect={() => togglePrompt(p.id)}
                      onPreview={() => setPreviewPrompt(p)} />
                  ))}
                </div>
              </div>
              <div className="dashed-panel">
                <h4 style={{ margin: "0 0 12px" }}>Мої промпти ({(overview?.user_prompts || []).length})</h4>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  {(overview?.user_prompts || []).map(p => (
                    <PromptCard key={p.id} prompt={p}
                      selected={selectedPromptIds.has(p.id)}
                      onSelect={() => togglePrompt(p.id)}
                      onPreview={() => setPreviewPrompt(p)} />
                  ))}
                  <div style={{ border: "1px dashed var(--line)", borderRadius: 10, padding: "10px 12px", minWidth: 140 }}>
                    <input placeholder="Назва промпту" value={newPromptName} onChange={e => setNewPromptName(e.target.value)}
                      style={{ marginBottom: 6 }} />
                    <textarea placeholder="Текст промпту…" value={newPromptText} onChange={e => setNewPromptText(e.target.value)} rows={3}
                      style={{ marginBottom: 6, resize: "none", width: "100%" }} />
                    <button type="button" className="ghost-button" style={{ fontSize: 12, width: "100%" }}
                      disabled={creatingPrompt} onClick={handleCreatePrompt}>+ Створити</button>
                  </div>
                </div>
                {(overview?.user_prompts || []).length > 0 && (
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
                    {(overview?.user_prompts || []).map(p => (
                      <button key={p.id} type="button" className="ghost-button" style={{ fontSize: 11, color: "var(--red)" }}
                        onClick={() => handleDeletePrompt(p)}>✕ {p.name}</button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        <div style={{ marginTop: 20 }}>
          <div className="section-title" style={{ marginBottom: 10 }}>
            <span style={{ fontSize: 18 }}>🌐</span>
            <h4 style={{ margin: 0, fontWeight: 600 }}>Мова коментарів</h4>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {[["auto", "⚡ Авто"], ["manual", "≡ Ручний"]].map(([v, l]) => (
              <button key={v} type="button" className={`ghost-button${form.language_mode === v ? " active" : ""}`}
                style={{ padding: "4px 16px", fontWeight: 500,
                  border: form.language_mode === v ? "2px solid var(--blue)" : undefined,
                  background: form.language_mode === v ? "rgba(27,164,255,0.12)" : undefined }}
                onClick={() => setField("language_mode", v)}>{l}</button>
            ))}
            {form.language_mode === "manual" && (
              <select value={form.language} onChange={e => setField("language", e.target.value)}>
                <option value="ru">🇷🇺 Русский</option>
                <option value="uk">🇺🇦 Українська</option>
                <option value="en">🇬🇧 English</option>
                <option value="de">🇩🇪 Deutsch</option>
                <option value="fr">🇫🇷 Français</option>
              </select>
            )}
          </div>
        </div>
      </section>

      {/* Timing / delays */}
      <section className="warmup-card danger-soft">
        <div className="section-title">
          <span className="section-icon red">◇</span>
          <div><h3>Ліміти та затримки</h3><p>Захист від flood-wait під час коментування</p></div>
          <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
            {[["Мін", 10, 30, 30, 60], ["Рекомендовані", 53, 99, 84, 156], ["Макс", 120, 240, 180, 360]].map(([l, cmin, cmax, emin, emax]) => (
              <button key={l} type="button" className="ghost-button" style={{ fontSize: 11, padding: "2px 10px" }}
                onClick={() => { setField("comment_delay_min", cmin); setField("comment_delay_max", cmax); setField("entry_delay_min", emin); setField("entry_delay_max", emax); }}>{l}</button>
            ))}
          </div>
        </div>
        <div className="warmup-grid two">
          <div className="dashed-panel">
            <h4 style={{ margin: "0 0 14px" }}>Затримка перед коментарем</h4>
            <div className="field-row">
              <label>Мін (с)<input type="number" min={0} value={form.comment_delay_min} onChange={e => setField("comment_delay_min", +e.target.value)} /></label>
              <label>Макс (с)<input type="number" min={0} value={form.comment_delay_max} onChange={e => setField("comment_delay_max", +e.target.value)} /></label>
            </div>
          </div>
          <div className="dashed-panel">
            <h4 style={{ margin: "0 0 14px" }}>Затримка входу в канал</h4>
            <div className="field-row">
              <label>Мін (с)<input type="number" min={0} value={form.entry_delay_min} onChange={e => setField("entry_delay_min", +e.target.value)} /></label>
              <label>Макс (с)<input type="number" min={0} value={form.entry_delay_max} onChange={e => setField("entry_delay_max", +e.target.value)} /></label>
            </div>
          </div>
        </div>
      </section>

      {/* Work modes */}
      <section className="warmup-card success-soft">
        <div className="section-title">
          <span className="section-icon green">⚙</span>
          <div><h3>Режим роботи</h3><p>Коментування, тривалість, ротація акаунтів</p></div>
        </div>
        <div className="warmup-grid two">
          <div className="dashed-panel">
            <h4 style={{ margin: "0 0 14px" }}>Режим коментування</h4>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
              {[["all", "Всі пости"], ["keyword", "За ключовими словами"], ["random", "Випадкові"]].map(([v, l]) => (
                <button key={v} type="button" className="ghost-button"
                  style={{ fontSize: 12, padding: "4px 12px",
                    border: form.comment_mode === v ? "2px solid var(--blue)" : undefined,
                    background: form.comment_mode === v ? "rgba(27,164,255,0.12)" : undefined }}
                  onClick={() => setField("comment_mode", v)}>{l}</button>
              ))}
            </div>
            {form.comment_mode === "keyword" && (
              <textarea value={keywordsText} onChange={e => setKeywordsText(e.target.value)}
                placeholder="Ключові слова (кожне з нового рядка)" rows={3}
                style={{ width: "100%", resize: "vertical" }} />
            )}
            {form.comment_mode === "random" && (
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: 13 }}>Ймовірність:</span>
                <input type="range" min={0} max={1} step={0.05} value={form.random_probability}
                  onChange={e => setField("random_probability", +e.target.value)} style={{ flex: 1 }} />
                <b style={{ fontSize: 13 }}>{Math.round(form.random_probability * 100)}%</b>
              </div>
            )}

            <h4 style={{ margin: "18px 0 10px" }}>Режим тривалості</h4>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              {[["monitoring", "Моніторинг"], ["count", "За кількістю"]].map(([v, l]) => (
                <button key={v} type="button" className="ghost-button"
                  style={{ fontSize: 12, padding: "4px 12px",
                    border: form.work_mode === v ? "2px solid var(--blue)" : undefined,
                    background: form.work_mode === v ? "rgba(27,164,255,0.12)" : undefined }}
                  onClick={() => setField("work_mode", v)}>{l}</button>
              ))}
            </div>
            {form.work_mode === "monitoring" && (
              <div className="field-row">
                <label>Тривалість (хв)<input type="number" min={5} value={form.duration_minutes} onChange={e => setField("duration_minutes", +e.target.value)} /></label>
              </div>
            )}
            {form.work_mode === "count" && (
              <div className="field-row">
                <label>Макс. коментарів<input type="number" min={1} value={form.max_comments} onChange={e => setField("max_comments", +e.target.value)} /></label>
              </div>
            )}
          </div>
          <div className="dashed-panel">
            <h4 style={{ margin: "0 0 14px" }}>Ротація акаунтів</h4>
            <Toggle checked={form.account_rotation} onChange={v => setField("account_rotation", v)}
              label="Ротація акаунтів" note="Автоматично змінювати акаунт після N коментарів" />
            {form.account_rotation && (
              <div className="field-row" style={{ marginTop: 12 }}>
                <label>Змінювати кожні N коментарів<input type="number" min={1} max={100} value={form.rotation_every_n} onChange={e => setField("rotation_every_n", +e.target.value)} /></label>
              </div>
            )}

            <h4 style={{ margin: "18px 0 10px" }}>Від кого писати</h4>
            <Toggle checked={form.write_as_channel} onChange={v => setField("write_as_channel", v)}
              label="Писати від імені каналу" note="Потрібен Telegram Premium" />
            {form.write_as_channel && (
              <div className="field-row" style={{ marginTop: 10 }}>
                <label>Username каналу<input placeholder="@channel_username" value={form.write_as_channel_username} onChange={e => setField("write_as_channel_username", e.target.value)} /></label>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Special features */}
      <section className="warmup-card">
        <div className="section-title">
          <span className="section-icon violet">◈</span>
          <div><h3>Спеціальні функції</h3><p>Автовідповідь та стратегія першого повідомлення</p></div>
        </div>
        <div className="warmup-grid two">
          <div className="dashed-panel">
            <Toggle checked={form.auto_reply_enabled} onChange={v => setField("auto_reply_enabled", v)}
              label="Автовідповідач" note="Автоматично відповідати у ЛС" />
            {form.auto_reply_enabled && (
              <textarea value={form.auto_reply_message} onChange={e => setField("auto_reply_message", e.target.value)}
                placeholder="Повідомлення для автовідповіді у ЛС…"
                rows={3} style={{ marginTop: 10, width: "100%", resize: "vertical" }} />
            )}
          </div>
          <div className="dashed-panel">
            <Toggle checked={form.first_message_strategy} onChange={v => setField("first_message_strategy", v)}
              label="Стратегія першого повідомлення" note="Спочатку надсилає emoji, потім редагує на коментар" />
            {form.first_message_strategy && (
              <div className="field-row" style={{ marginTop: 12 }}>
                <label>Emoji<input value={form.first_message_text} onChange={e => setField("first_message_text", e.target.value)} style={{ textAlign: "center", fontSize: 18 }} /></label>
                <label>Затримка редагування (с)<input type="number" min={5} value={form.first_message_edit_delay} onChange={e => setField("first_message_edit_delay", +e.target.value)} /></label>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* AI Protection */}
      <section className="warmup-card">
        <div className="section-title">
          <span className="section-icon green">🛡</span>
          <div><h3>AI захист від блокувань</h3><p>Симулює людську поведінку: затримки, набір тексту, перегляди профілів, опечатки</p></div>
          <div style={{ marginLeft: "auto" }}>
            <Toggle checked={form.ai_protection} onChange={v => setField("ai_protection", v)} label="" />
          </div>
        </div>
        {form.ai_protection && (
          <div className="intensity-list">
            {[
              ["safe", "🛡 Консервативний", "x1.5 затримки · набір 40-60 cpm · сон 01:00-07:00 · перегляд профілів 90% · опечатки 8%"],
              ["balanced", "⚖ Збалансований", "x1.0 затримки · набір 100-150 cpm · сон 02:00-07:00 · перегляд 70% · опечатки 5% (рекомендовано)"],
              ["fast", "⚡ Агресивний", "x0.7 затримки · набір вимкнено · без нічного сну · перегляд 30% · опечатки 2%"],
            ].map(([v, title, desc]) => (
              <button key={v} type="button"
                className={form.protection_mode === v ? "active" : ""}
                onClick={() => setField("protection_mode", v)}>
                <b>{title}</b>
                <span>{desc}</span>
              </button>
            ))}
          </div>
        )}
      </section>

      {/* Job name + Launch */}
      <section className="warmup-card launch-panel">
        <div className="launch-stats">
          <div><span>Акаунти</span><b>{selectedAccountIds.size}</b></div>
          <div><span>Канали</span><b>{parseSources().length}</b></div>
          <div><span>Захист</span><b>{form.ai_protection ? form.protection_mode : "вимк"}</b></div>
          <div><span>Статус</span><b>{editingJob ? "Редагування" : "Нова задача"}</b></div>
        </div>
        <div style={{ marginTop: 16 }}>
          <label>Назва задачі
            <input value={form.name} onChange={e => setField("name", e.target.value)} />
          </label>
          {saveError && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 8 }}>{saveError}</div>}
          <div className="launch-box" style={{ marginTop: 14 }}>
            <button className="primary-button big" disabled={saving} onClick={handleSave}>
              {saving ? "Збереження…" : editingJob ? "▷ Зберегти зміни" : "▷ Створити задачу"}
            </button>
            {editingJob && (
              <button className="ghost-button" onClick={cancelEdit}>Скасувати</button>
            )}
          </div>
        </div>
      </section>

      {/* Jobs list */}
      <section className="warmup-card">
        <div className="section-title">
          <span className="section-icon blue">☰</span>
          <div><h3>Задачі ({(overview?.jobs || []).length})</h3><p>Активні та завершені задачі коментування</p></div>
          <button className="ghost-button" style={{ marginLeft: "auto" }} onClick={clearFinished}>Очистити завершені</button>
        </div>
        <div className="plan-grid">
          {(overview?.jobs || []).length === 0 && <div className="empty-state">Задач ще немає</div>}
          {(overview?.jobs || []).map(job => (
            <article key={job.id} className="plan-card">
              <div><b>{job.name}</b><span>{formatDate(job.created_at)} · {job.comments_sent} коментарів</span></div>
              <strong className={`badge ${statusBadge(job.status)}`}>{statusLabel(job.status)}</strong>
              {job.error && <small style={{ color: "var(--red)" }}>{job.error}</small>}
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                {job.status !== "running" && (
                  <button type="button" className="ghost-button" style={{ fontSize: 12, background: "rgba(28,201,138,0.15)", color: "var(--green)" }}
                    onClick={() => handleStart(job)}>▶ Запустити</button>
                )}
                {job.status === "running" && (
                  <button type="button" className="ghost-button" style={{ fontSize: 12, background: "rgba(243,95,111,0.15)", color: "var(--red)" }}
                    onClick={() => handleStop(job)}>⏹ Зупинити</button>
                )}
                <button type="button" className="ghost-button" style={{ fontSize: 12 }} onClick={() => startEdit(job)}>✏ Редагувати</button>
                <button type="button" className="ghost-button" style={{ fontSize: 12, color: "var(--red)" }} onClick={() => handleDelete(job)}>✕</button>
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* Logs */}
      <section className="warmup-card logs-card">
        <div className="log-toolbar">
          <span className="online-dot">● логи</span>
          <span>Усі {logs.length}</span>
          {["info", "success", "warning", "error"].map(l => (
            <button key={l} type="button"
              className={logFilter === l ? "active" : ""}
              onClick={() => setLogFilter(logFilter === l ? "all" : l)}>
              {l} {logs.filter(x => x.level === l).length}
            </button>
          ))}
        </div>
        <div className="terminal">
          {filteredLogs.length === 0 && <div className="empty-state">Логів поки немає</div>}
          {[...filteredLogs].reverse().map(log => (
            <div key={log.id} className={`terminal-line ${levelClass(log.level)}`}>
              <time>{new Date(log.created_at).toLocaleTimeString("uk-UA")}</time>
              <span>{log.level === "error" ? "❌" : log.level === "warning" ? "⚠️" : "✅"}</span>
              <b>{log.account_label || "system"}</b>
              <p>{log.message}{log.comment_text ? ` 💬 ${log.comment_text.slice(0, 60)}` : ""}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Blacklist */}
      <section className="warmup-card">
        <div className="section-title">
          <span className="section-icon red">🚫</span>
          <div><h3>Чорний список</h3><p>Канали з помилками, куди бот тимчасово не коментуватиме</p></div>
          <div style={{ display: "flex", gap: 8, marginLeft: "auto" }}>
            <select value={blacklistFilter} onChange={e => setBlacklistFilter(e.target.value)}>
              <option value="all">Всі акаунти</option>
              {blacklistAccounts.map(a => <option key={a} value={a}>{a}</option>)}
            </select>
            <button type="button" className="ghost-button" style={{ color: "var(--red)" }} onClick={clearBlacklist}>Очистити все</button>
          </div>
        </div>
        {filteredBlacklist.length === 0 ? (
          <div style={{ textAlign: "center", padding: "30px 0" }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>✅</div>
            <b>В чорному списку немає груп</b>
            <p style={{ color: "var(--muted)", fontSize: 13 }}>Групи будуть автоматично додані при виникненні помилок</p>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {filteredBlacklist.map(item => (
              <div key={item.id} style={{
                display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 8, alignItems: "center",
                padding: "10px 14px", borderRadius: 10, background: "rgba(255,255,255,0.04)", border: "1px solid var(--line)",
              }}>
                <div><div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 2 }}>АКАУНТ</div><div style={{ fontSize: 13 }}>{item.account_label || "—"}</div></div>
                <div><div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 2 }}>ПРИЧИНА</div><div style={{ fontSize: 13 }}>{item.reason}</div></div>
                <div><div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 2 }}>КАНАЛ</div><div style={{ fontSize: 13 }}>@{item.channel_username}</div></div>
                <button type="button" className="ghost-button" style={{ color: "var(--red)" }} onClick={() => handleDeleteBlacklist(item)}>✕</button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Prompt preview modal */}
      {previewPrompt && (
        <div
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}
          onClick={() => setPreviewPrompt(null)}
        >
          <div
            style={{ background: "var(--panel-strong)", borderRadius: 16, padding: 28, maxWidth: 480, width: "90%", boxShadow: "var(--shadow)", border: "1px solid var(--line)" }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 12 }}>{previewPrompt.name}</div>
            <div style={{ color: "var(--muted)", fontSize: 14, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{previewPrompt.text}</div>
            <button type="button" className="ghost-button" style={{ marginTop: 16, width: "100%" }} onClick={() => setPreviewPrompt(null)}>Закрити</button>
          </div>
        </div>
      )}
    </AppShell>
  );
}
