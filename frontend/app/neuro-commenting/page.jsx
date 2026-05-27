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
    <label className="toggle-line parser-toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="switch" />
      <span>
        <b>{label}</b>
        {note ? <small>{note}</small> : null}
      </span>
    </label>
  );
}

function RangeRow({ label, minVal, maxVal, onMin, onMax, unit = "с", presets }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <span style={{ fontSize: 13, fontWeight: 500 }}>{label}</span>
        {presets && (
          <div style={{ display: "flex", gap: 6 }}>
            {presets.map(([l, min, max]) => (
              <button key={l} type="button" className="ghost-button" style={{ fontSize: 11, padding: "2px 8px" }}
                onClick={() => { onMin(min); onMax(max); }}>{l}</button>
            ))}
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <input type="number" min={0} value={minVal} onChange={e => onMin(+e.target.value)}
          style={{ width: 80, padding: "4px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)" }} />
        <span style={{ color: "var(--text-muted)", fontSize: 12 }}>–</span>
        <input type="number" min={0} value={maxVal} onChange={e => onMax(+e.target.value)}
          style={{ width: 80, padding: "4px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)" }} />
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{unit} ({minVal}–{maxVal} {unit})</span>
      </div>
    </div>
  );
}

function AccountPicker({ all, selected, onChange }) {
  const selectedSet = new Set(selected);
  const toggle = (id) => {
    if (selectedSet.has(id)) onChange(selected.filter(x => x !== id));
    else onChange([...selected, id]);
  };
  const addAll = () => onChange(all.map(a => a.id));
  const removeAll = () => onChange([]);

  return (
    <div className="parser-account-picker" style={{ display: "flex", gap: 16 }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>
          Доступні акаунти ({all.length})
        </div>
        <div style={{ marginBottom: 8 }}>
          <button type="button" className="ghost-button" style={{ fontSize: 12 }} onClick={addAll}>Додати всі</button>
        </div>
        <div style={{ maxHeight: 260, overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 }}>
          {all.map(a => (
            <div key={a.id}
              style={{
                padding: "8px 12px", borderRadius: 8,
                border: selectedSet.has(a.id) ? "1px solid var(--accent)" : "1px solid var(--border)",
                background: selectedSet.has(a.id) ? "var(--accent-soft)" : "var(--surface-2)",
                cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center",
              }}
              onClick={() => toggle(a.id)}>
              <div>
                <div style={{ fontWeight: 500, fontSize: 13 }}>{a.label}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{a.phone_number}</div>
              </div>
              <div style={{ fontSize: 11, padding: "2px 6px", borderRadius: 4, background: a.status === "active" ? "#22c55e22" : "#f59e0b22", color: a.status === "active" ? "#22c55e" : "#f59e0b" }}>
                {a.status === "active" ? "Активний" : a.status}
              </div>
            </div>
          ))}
          {all.length === 0 && <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Немає підключених акаунтів</div>}
        </div>
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Вибрано ({selected.length})</div>
          <button type="button" className="ghost-button" style={{ fontSize: 12, color: "#ef4444" }} onClick={removeAll}>Видалити всі</button>
        </div>
        <div style={{ maxHeight: 260, overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 }}>
          {selected.length === 0 && (
            <div style={{ color: "var(--text-muted)", fontSize: 13, textAlign: "center", marginTop: 40 }}>Акаунти не вибрані</div>
          )}
          {all.filter(a => selectedSet.has(a.id)).map(a => (
            <div key={a.id}
              style={{
                padding: "8px 12px", borderRadius: 8,
                border: "1px solid var(--accent)", background: "var(--accent-soft)",
                cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center",
              }}
              onClick={() => toggle(a.id)}>
              <div>
                <div style={{ fontWeight: 500, fontSize: 13 }}>{a.label}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{a.phone_number}</div>
              </div>
              <span style={{ fontSize: 16, color: "#ef4444" }}>×</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function PromptCard({ prompt, selected, onSelect, onPreview }) {
  return (
    <div style={{
      border: selected ? "2px solid var(--accent)" : "1px solid var(--border)",
      borderRadius: 10, padding: "12px 14px", cursor: "pointer", position: "relative",
      background: selected ? "var(--accent-soft)" : "var(--surface-2)",
      minWidth: 140, maxWidth: 180,
    }} onClick={onSelect}>
      {selected && (
        <div style={{
          position: "absolute", top: -8, right: -8, width: 20, height: 20,
          borderRadius: "50%", background: "var(--accent)", color: "#fff",
          display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12,
        }}>✓</div>
      )}
      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>{prompt.name}</div>
      <div style={{ display: "flex", gap: 6 }}>
        <button type="button" className="ghost-button" style={{ fontSize: 11, padding: "2px 8px" }}
          onClick={(e) => { e.stopPropagation(); onPreview(prompt); }}>👁</button>
        <button type="button" className="ghost-button" style={{ fontSize: 11, padding: "2px 8px" }}
          onClick={onSelect}>▶</button>
      </div>
    </div>
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

function statusClass(s) {
  if (s === "running") return "info";
  if (s === "succeeded") return "success";
  if (s === "failed") return "error";
  if (s === "stopped") return "warning";
  return "";
}

function levelClass(l) {
  if (l === "success") return "success";
  if (l === "error") return "error";
  if (l === "warning") return "warning";
  return "info";
}

export default function NeuroCommentingPage() {
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [form, setForm] = useState(defaultForm);
  const [editingJob, setEditingJob] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [activeTab, setActiveTab] = useState("accounts");
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

  const runningJob = overview?.jobs?.find(j => j.status === "running");

  const setField = (key, val) => setForm(prev => ({ ...prev, [key]: val }));

  const parseSources = () => {
    return sourcesText.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);
  };
  const parseKeywords = () => {
    return keywordsText.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);
  };

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
    });
    setSourcesText((job.sources || []).join("\n"));
    setKeywordsText((job.keywords || []).join("\n"));
  };

  const cancelEdit = () => { setEditingJob(null); setForm(defaultForm); setSourcesText(""); setKeywordsText(""); setSaveError(""); };

  const handleSave = async () => {
    setSaving(true); setSaveError("");
    const payload = {
      ...form,
      sources: parseSources(),
      keywords: parseKeywords(),
      accounts: form.accounts || [],
    };
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
      setNewPromptName(""); setNewPromptText("");
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

  const allPrompts = [...(overview?.system_prompts || []), ...(overview?.user_prompts || [])];
  const selectedPromptIds = new Set(form.selected_prompts || []);
  const togglePrompt = (id) => {
    if (selectedPromptIds.has(id)) setField("selected_prompts", [...selectedPromptIds].filter(x => x !== id));
    else setField("selected_prompts", [...selectedPromptIds, id]);
  };

  const blacklist = overview?.blacklist || [];
  const filteredBlacklist = blacklistFilter === "all" ? blacklist
    : blacklist.filter(b => b.account_label === blacklistFilter);
  const blacklistAccounts = [...new Set(blacklist.map(b => b.account_label).filter(Boolean))];

  if (loading && !overview) return (
    <AppShell>
      <div className="parser-page"><div style={{ color: "var(--text-muted)" }}>Завантаження…</div></div>
    </AppShell>
  );

  return (
    <AppShell>
      <div className="parser-page">
        {/* Hero */}
        <div className="parser-hero">
          <h2>Нейрокоментинг</h2>
          <p>Автоматичне коментування постів у Telegram-каналах за допомогою ШІ.</p>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 8 }}>
            <a href="#" className="ghost-button" style={{ fontSize: 12 }}>ℹ О модулі</a>
            <a href="#" className="ghost-button" style={{ fontSize: 12 }}>📄 Статті</a>
          </div>
        </div>

        {error && <div style={{ background: "#ef444422", color: "#ef4444", padding: "8px 14px", borderRadius: 8, marginBottom: 16 }}>{error}</div>}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
          {/* LEFT — Config */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

            {/* Accounts section */}
            <div className="parser-run-card" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 18px", background: "var(--surface-2)", borderBottom: "1px solid var(--border)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ background: "#3b82f6", borderRadius: 8, padding: "4px 8px", fontSize: 16 }}>👥</span>
                  <b>Вибір акаунтів</b>
                  <span className="tag">{(form.accounts || []).length} вибрано</span>
                  <span className="tag">{overview?.accounts?.length || 0}/{Math.max(overview?.accounts?.length || 0, 50)}</span>
                </div>
              </div>
              <div style={{ padding: 18 }}>
                <AccountPicker
                  all={overview?.accounts || []}
                  selected={form.accounts || []}
                  onChange={v => setField("accounts", v)}
                />
              </div>
            </div>

            {/* Target channels */}
            <div className="parser-run-card" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 18px", background: "var(--surface-2)", borderBottom: "1px solid var(--border)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ background: "#8b5cf6", borderRadius: 8, padding: "4px 8px", fontSize: 16 }}>#</span>
                  <b>Цільові канали</b>
                  <span className="tag">{parseSources().length}</span>
                </div>
              </div>
              <div style={{ padding: 18 }}>
                <div style={{ marginBottom: 10, fontSize: 13, color: "var(--text-muted)" }}>
                  @username, https://t.me/channel_name або папка https://t.me/addlist/&lt;slug&gt; — кожен запис з нового рядка
                </div>
                <textarea
                  value={sourcesText}
                  onChange={e => setSourcesText(e.target.value)}
                  placeholder={"@channel1\nhttps://t.me/channel2\nhttps://t.me/addlist/AbCdEfGh"}
                  rows={6}
                  style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)", resize: "vertical", fontFamily: "monospace", fontSize: 13 }}
                />
                <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>
                  Папку Telegram (t.me/addlist/…) безпечніше додавати замість 50 окремих каналів — це один join-виклик замість десятків,
                  що різко знижує ризик flood-wait. Для приватних каналів додавайте 5–15 на день.
                </div>
              </div>
            </div>

            {/* Message settings */}
            <div className="parser-run-card" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ padding: "14px 18px", background: "var(--surface-2)", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ background: "#ec4899", borderRadius: 8, padding: "4px 8px", fontSize: 16 }}>✦</span>
                <b>Налаштування повідомлень</b>
              </div>
              <div style={{ padding: 18 }}>
                <Toggle checked={form.use_ai_prompt} onChange={v => setField("use_ai_prompt", v)} label="Використовувати AI промпт" note="ШІ генерує коментар на основі тексту поста" />

                {form.use_ai_prompt && (
                  <>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginTop: 16, marginBottom: 8 }}>Системні ({(overview?.system_prompts || []).length})</div>
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
                      {(overview?.system_prompts || []).map(p => (
                        <PromptCard key={p.id} prompt={p}
                          selected={selectedPromptIds.has(p.id)}
                          onSelect={() => togglePrompt(p.id)}
                          onPreview={() => setPreviewPrompt(p)} />
                      ))}
                    </div>

                    <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 8 }}>Мої промпти ({(overview?.user_prompts || []).length})</div>
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
                      {(overview?.user_prompts || []).map(p => (
                        <PromptCard key={p.id} prompt={p}
                          selected={selectedPromptIds.has(p.id)}
                          onSelect={() => togglePrompt(p.id)}
                          onPreview={() => setPreviewPrompt(p)} />
                      ))}
                      {/* Create prompt */}
                      <div style={{
                        border: "1px dashed var(--border)", borderRadius: 10, padding: "12px 14px",
                        cursor: "pointer", minWidth: 140, maxWidth: 200, background: "var(--surface)",
                      }}>
                        <input placeholder="Назва промпту" value={newPromptName} onChange={e => setNewPromptName(e.target.value)}
                          style={{ width: "100%", marginBottom: 6, padding: "4px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)", fontSize: 12 }} />
                        <textarea placeholder="Текст промпту…" value={newPromptText} onChange={e => setNewPromptText(e.target.value)} rows={3}
                          style={{ width: "100%", marginBottom: 6, padding: "4px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)", fontSize: 12, resize: "none" }} />
                        <button type="button" className="ghost-button" style={{ fontSize: 12, width: "100%" }}
                          disabled={creatingPrompt} onClick={handleCreatePrompt}>+ Створити</button>
                      </div>
                    </div>

                    {/* User prompts delete */}
                    {(overview?.user_prompts || []).length > 0 && (
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {(overview?.user_prompts || []).map(p => (
                          <button key={p.id} type="button" className="ghost-button" style={{ fontSize: 11, color: "#ef4444" }}
                            onClick={() => handleDeletePrompt(p)}>✕ {p.name}</button>
                        ))}
                      </div>
                    )}
                  </>
                )}

                {/* Language mode */}
                <div style={{ marginTop: 18, marginBottom: 12, display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontSize: 16 }}>🌐</span>
                  <b style={{ fontSize: 13 }}>Режим визначення мови</b>
                </div>
                <div style={{ display: "flex", gap: 8, marginBottom: form.language_mode === "manual" ? 10 : 0 }}>
                  {[["auto", "Авто"], ["manual", "Ручний"]].map(([v, l]) => (
                    <button key={v} type="button"
                      className={form.language_mode === v ? "ghost-button" : "ghost-button"}
                      style={{ padding: "4px 14px", borderRadius: 20, fontWeight: 500, fontSize: 13,
                        border: form.language_mode === v ? "2px solid var(--accent)" : "1px solid var(--border)",
                        background: form.language_mode === v ? "var(--accent-soft)" : "transparent" }}
                      onClick={() => setField("language_mode", v)}>{v === "auto" ? "⚡ Авто" : "≡ Ручний"}</button>
                  ))}
                  {form.language_mode === "manual" && (
                    <select value={form.language} onChange={e => setField("language", e.target.value)}
                      style={{ padding: "4px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)", fontSize: 13 }}>
                      <option value="ru">🇷🇺 Русский</option>
                      <option value="uk">🇺🇦 Українська</option>
                      <option value="en">🇬🇧 English</option>
                      <option value="de">🇩🇪 Deutsch</option>
                      <option value="fr">🇫🇷 Français</option>
                    </select>
                  )}
                </div>
              </div>
            </div>

            {/* Additional settings */}
            <div className="parser-run-card" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ padding: "14px 18px", background: "var(--surface-2)", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ background: "#374151", borderRadius: 8, padding: "4px 8px", fontSize: 16 }}>⏱</span>
                <b>Додаткові налаштування</b>
                <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
                  {[["Мін", 10, 30, 30, 60], ["Рекомендовані", 53, 99, 84, 156], ["Макс", 120, 240, 180, 360]].map(([l, cmin, cmax, emin, emax]) => (
                    <button key={l} type="button" className="ghost-button" style={{ fontSize: 11, padding: "2px 10px" }}
                      onClick={() => { setField("comment_delay_min", cmin); setField("comment_delay_max", cmax); setField("entry_delay_min", emin); setField("entry_delay_max", emax); }}>{l}</button>
                  ))}
                </div>
              </div>
              <div style={{ padding: 18 }}>
                <RangeRow label="Затримка перед коментарем"
                  minVal={form.comment_delay_min} maxVal={form.comment_delay_max}
                  onMin={v => setField("comment_delay_min", v)} onMax={v => setField("comment_delay_max", v)} />
                <RangeRow label="Затримка входу в канал"
                  minVal={form.entry_delay_min} maxVal={form.entry_delay_max}
                  onMin={v => setField("entry_delay_min", v)} onMax={v => setField("entry_delay_max", v)} />

                {/* Comment mode */}
                <div style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 6 }}>Режим коментування</div>
                  <div style={{ display: "flex", gap: 8 }}>
                    {[["all", "Всі пости"], ["keyword", "За ключовими словами"], ["random", "Випадкові"]].map(([v, l]) => (
                      <button key={v} type="button" className="ghost-button"
                        style={{ fontSize: 12, padding: "4px 12px",
                          border: form.comment_mode === v ? "2px solid var(--accent)" : "1px solid var(--border)",
                          background: form.comment_mode === v ? "var(--accent-soft)" : "transparent" }}
                        onClick={() => setField("comment_mode", v)}>{l}</button>
                    ))}
                  </div>
                  {form.comment_mode === "keyword" && (
                    <textarea value={keywordsText} onChange={e => setKeywordsText(e.target.value)}
                      placeholder="Ключові слова (кожне з нового рядка)"
                      rows={3} style={{ marginTop: 8, width: "100%", padding: "6px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)", resize: "vertical", fontSize: 13 }} />
                  )}
                  {form.comment_mode === "random" && (
                    <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontSize: 13 }}>Ймовірність:</span>
                      <input type="range" min={0} max={1} step={0.05} value={form.random_probability}
                        onChange={e => setField("random_probability", +e.target.value)} style={{ flex: 1 }} />
                      <span style={{ fontSize: 13, fontWeight: 600 }}>{Math.round(form.random_probability * 100)}%</span>
                    </div>
                  )}
                </div>

                {/* Work mode */}
                <div style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 6 }}>Режим роботи</div>
                  <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
                    {[["monitoring", "Моніторинг"], ["count", "За кількістю"]].map(([v, l]) => (
                      <button key={v} type="button" className="ghost-button"
                        style={{ fontSize: 12, padding: "4px 12px",
                          border: form.work_mode === v ? "2px solid var(--accent)" : "1px solid var(--border)",
                          background: form.work_mode === v ? "var(--accent-soft)" : "transparent" }}
                        onClick={() => setField("work_mode", v)}>{l}</button>
                    ))}
                  </div>
                  {form.work_mode === "monitoring" && (
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontSize: 13 }}>Тривалість:</span>
                      <input type="number" min={5} value={form.duration_minutes} onChange={e => setField("duration_minutes", +e.target.value)}
                        style={{ width: 80, padding: "4px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)" }} />
                      <span style={{ fontSize: 13, color: "var(--text-muted)" }}>хв</span>
                    </div>
                  )}
                  {form.work_mode === "count" && (
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontSize: 13 }}>Макс. коментарів:</span>
                      <input type="number" min={1} value={form.max_comments} onChange={e => setField("max_comments", +e.target.value)}
                        style={{ width: 100, padding: "4px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)" }} />
                    </div>
                  )}
                </div>

                {/* Account rotation */}
                <Toggle checked={form.account_rotation} onChange={v => setField("account_rotation", v)}
                  label="Ротація акаунтів" note="Автоматично змінювати акаунт після N коментарів" />
                {form.account_rotation && (
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8, marginLeft: 32 }}>
                    <span style={{ fontSize: 13 }}>Змінювати кожні</span>
                    <input type="number" min={1} max={100} value={form.rotation_every_n} onChange={e => setField("rotation_every_n", +e.target.value)}
                      style={{ width: 70, padding: "4px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)" }} />
                    <span style={{ fontSize: 13 }}>коментарів</span>
                  </div>
                )}

                {/* Write as channel */}
                <div style={{ marginTop: 14 }}>
                  <Toggle checked={form.write_as_channel} onChange={v => setField("write_as_channel", v)}
                    label="Писати від імені каналу" note="Потрібен Telegram Premium" />
                  {form.write_as_channel && (
                    <input placeholder="@channel_username" value={form.write_as_channel_username} onChange={e => setField("write_as_channel_username", e.target.value)}
                      style={{ marginTop: 8, marginLeft: 32, width: "calc(100% - 32px)", padding: "6px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)", fontSize: 13 }} />
                  )}
                </div>

                {/* Auto-reply */}
                <div style={{ marginTop: 14 }}>
                  <Toggle checked={form.auto_reply_enabled} onChange={v => setField("auto_reply_enabled", v)}
                    label="Автовідповідач" note="Автоматично відповідати у ЛС" />
                  {form.auto_reply_enabled && (
                    <textarea value={form.auto_reply_message} onChange={e => setField("auto_reply_message", e.target.value)}
                      placeholder="Введіть повідомлення для автоматичної відповіді у ЛС…"
                      rows={3} style={{ marginTop: 8, width: "100%", padding: "6px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)", resize: "vertical", fontSize: 13 }} />
                  )}
                </div>

                {/* First message strategy */}
                <div style={{ marginTop: 14 }}>
                  <Toggle checked={form.first_message_strategy} onChange={v => setField("first_message_strategy", v)}
                    label="Стратегія першого повідомлення" note="Спочатку надсилає emoji, потім редагує на коментар" />
                  {form.first_message_strategy && (
                    <div style={{ marginTop: 8, marginLeft: 32, display: "flex", gap: 10, alignItems: "center" }}>
                      <input value={form.first_message_text} onChange={e => setField("first_message_text", e.target.value)}
                        style={{ width: 80, padding: "4px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)", fontSize: 16, textAlign: "center" }} />
                      <span style={{ fontSize: 13, color: "var(--text-muted)" }}>затримка редагування:</span>
                      <input type="number" min={5} value={form.first_message_edit_delay} onChange={e => setField("first_message_edit_delay", +e.target.value)}
                        style={{ width: 70, padding: "4px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)" }} />
                      <span style={{ fontSize: 13, color: "var(--text-muted)" }}>с</span>
                    </div>
                  )}
                </div>

                {/* AI protection */}
                <div style={{ marginTop: 14 }}>
                  <Toggle checked={form.ai_protection} onChange={v => setField("ai_protection", v)}
                    label="AI захист від блокувань" note="Симулює людську поведінку (затримки, друк, перегляд профілів, опечатки)" />
                  {form.ai_protection && (
                    <div style={{ marginTop: 10, paddingLeft: 28 }}>
                      <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>Режим</div>
                      <select
                        value={form.protection_mode}
                        onChange={e => setField("protection_mode", e.target.value)}
                        style={{ padding: "6px 10px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)", fontSize: 13 }}
                      >
                        <option value="safe">🛡 Консервативний — макс. безпека, повільно</option>
                        <option value="balanced">⚖ Збалансований — оптимально (рекомендовано)</option>
                        <option value="fast">⚡ Агресивний — швидко, мінімальний захист</option>
                      </select>
                      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6, lineHeight: 1.4 }}>
                        {form.protection_mode === "safe" && "x1.5 затримки · набір 40-60 cpm · сон 01:00-07:00 · перегляд профілів 90% · опечатки 8%"}
                        {form.protection_mode === "balanced" && "x1.0 затримки · набір 100-150 cpm · сон 02:00-07:00 · перегляд 70% · опечатки 5%"}
                        {form.protection_mode === "fast" && "x0.7 затримки · набір вимкнено · без сну · перегляд 30% · опечатки 2%"}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Job name + save */}
            <div className="parser-run-card">
              <div style={{ marginBottom: 10 }}>
                <label style={{ fontSize: 13, fontWeight: 500 }}>Назва задачі</label>
                <input value={form.name} onChange={e => setField("name", e.target.value)}
                  style={{ marginTop: 4, width: "100%", padding: "8px 12px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)" }} />
              </div>
              {saveError && <div style={{ color: "#ef4444", fontSize: 13, marginBottom: 8 }}>{saveError}</div>}
              <div style={{ display: "flex", gap: 10 }}>
                <button type="button" className="parser-run-card" style={{ flex: 1, padding: "10px", textAlign: "center", background: "var(--accent)", color: "#fff", fontWeight: 600, border: "none", borderRadius: 10, cursor: "pointer" }}
                  disabled={saving} onClick={handleSave}>
                  {saving ? "Збереження…" : editingJob ? "Зберегти зміни" : "Створити задачу"}
                </button>
                {editingJob && (
                  <button type="button" className="ghost-button" onClick={cancelEdit}>Скасувати</button>
                )}
              </div>
            </div>
          </div>

          {/* RIGHT — Jobs list + logs + blacklist */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

            {/* Jobs */}
            <div className="parser-run-card" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ padding: "14px 18px", background: "var(--surface-2)", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <b>Задачі ({(overview?.jobs || []).length})</b>
                <button type="button" className="ghost-button" style={{ fontSize: 12 }} onClick={clearFinished}>Очистити завершені</button>
              </div>
              <div style={{ padding: 14, display: "flex", flexDirection: "column", gap: 10, maxHeight: 400, overflowY: "auto" }}>
                {(overview?.jobs || []).length === 0 && (
                  <div style={{ color: "var(--text-muted)", fontSize: 13, textAlign: "center", padding: 20 }}>Задач ще немає</div>
                )}
                {(overview?.jobs || []).map(job => (
                  <div key={job.id} style={{ border: "1px solid var(--border)", borderRadius: 10, padding: "12px 14px", background: "var(--surface-2)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                      <div>
                        <div style={{ fontWeight: 600, fontSize: 14 }}>{job.name}</div>
                        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                          {formatDate(job.created_at)} · Коментарів: {job.comments_sent}
                        </div>
                      </div>
                      <span className={`tag ${statusClass(job.status)}`}>{statusLabel(job.status)}</span>
                    </div>
                    {job.error && <div style={{ color: "#ef4444", fontSize: 12, marginTop: 6 }}>{job.error}</div>}
                    <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                      {job.status !== "running" && (
                        <button type="button" className="ghost-button" style={{ fontSize: 12, background: "#22c55e22", color: "#22c55e" }}
                          onClick={() => handleStart(job)}>▶ Запустити</button>
                      )}
                      {job.status === "running" && (
                        <button type="button" className="ghost-button" style={{ fontSize: 12, background: "#ef444422", color: "#ef4444" }}
                          onClick={() => handleStop(job)}>⏹ Зупинити</button>
                      )}
                      <button type="button" className="ghost-button" style={{ fontSize: 12 }} onClick={() => startEdit(job)}>✏ Редагувати</button>
                      <button type="button" className="ghost-button" style={{ fontSize: 12, color: "#ef4444" }} onClick={() => handleDelete(job)}>✕</button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Logs */}
            <div className="parser-run-card" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ padding: "14px 18px", background: "var(--surface-2)", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <b>Логи ({filteredLogs.length})</b>
                <div style={{ display: "flex", gap: 6 }}>
                  {["all", "info", "success", "warning", "error"].map(l => (
                    <button key={l} type="button" className="ghost-button"
                      style={{ fontSize: 11, padding: "2px 8px", border: logFilter === l ? "2px solid var(--accent)" : "1px solid var(--border)" }}
                      onClick={() => setLogFilter(l)}>{l}</button>
                  ))}
                </div>
              </div>
              <div className="parser-terminal" style={{ maxHeight: 320, overflowY: "auto" }}>
                {filteredLogs.length === 0 && (
                  <div style={{ color: "var(--text-muted)", padding: 12, fontSize: 13 }}>Логів немає</div>
                )}
                {[...filteredLogs].reverse().map(log => (
                  <div key={log.id} style={{ padding: "5px 12px", borderBottom: "1px solid var(--border)33", display: "flex", gap: 10, fontSize: 12 }}>
                    <span style={{ opacity: 0.5, whiteSpace: "nowrap" }}>{new Date(log.created_at).toLocaleTimeString("uk-UA")}</span>
                    <span className={`tag ${levelClass(log.level)}`} style={{ fontSize: 10 }}>{log.level}</span>
                    <span style={{ flex: 1, color: "var(--text)" }}>{log.message}</span>
                    {log.comment_text && <span style={{ color: "#8b5cf6", fontSize: 11 }}>💬 {log.comment_text.slice(0, 40)}</span>}
                  </div>
                ))}
              </div>
            </div>

            {/* Blacklist */}
            <div className="parser-run-card" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ padding: "14px 18px", background: "var(--surface-2)", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ background: "#ef4444", borderRadius: 8, padding: "4px 8px", fontSize: 16 }}>🚫</span>
                  <b>Чорний список</b>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <select value={blacklistFilter} onChange={e => setBlacklistFilter(e.target.value)}
                    style={{ padding: "4px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)", fontSize: 12 }}>
                    <option value="all">Всі акаунти</option>
                    {blacklistAccounts.map(a => <option key={a} value={a}>{a}</option>)}
                  </select>
                  <button type="button" className="ghost-button" style={{ fontSize: 12, color: "#ef4444" }} onClick={clearBlacklist}>Очистити все</button>
                </div>
              </div>
              <div style={{ padding: 14, display: "flex", flexDirection: "column", gap: 6, maxHeight: 260, overflowY: "auto" }}>
                {filteredBlacklist.length === 0 && (
                  <div style={{ textAlign: "center", padding: 20 }}>
                    <div style={{ fontSize: 32, marginBottom: 8 }}>✅</div>
                    <div style={{ fontWeight: 600, marginBottom: 4 }}>В чорному списку немає груп</div>
                    <div style={{ fontSize: 13, color: "var(--text-muted)" }}>Групи будуть автоматично додані при виникненні помилок</div>
                  </div>
                )}
                {filteredBlacklist.map(item => (
                  <div key={item.id} style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 8, alignItems: "center", padding: "8px 10px", borderRadius: 8, background: "var(--surface-2)", border: "1px solid var(--border)" }}>
                    <div>
                      <div style={{ fontSize: 13, color: "var(--text-muted)", fontSize: 11 }}>АКАУНТ</div>
                      <div style={{ fontSize: 13 }}>{item.account_label || "—"}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 11, color: "var(--text-muted)" }}>ПРИЧИНА</div>
                      <div style={{ fontSize: 13 }}>{item.reason}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 11, color: "var(--text-muted)" }}>КАНАЛ</div>
                      <div style={{ fontSize: 13 }}>@{item.channel_username}</div>
                    </div>
                    <button type="button" className="ghost-button" style={{ fontSize: 12, color: "#ef4444" }}
                      onClick={() => handleDeleteBlacklist(item)}>✕</button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Prompt preview modal */}
        {previewPrompt && (
          <div style={{
            position: "fixed", inset: 0, background: "#00000088", zIndex: 1000,
            display: "flex", alignItems: "center", justifyContent: "center",
          }} onClick={() => setPreviewPrompt(null)}>
            <div style={{ background: "var(--surface)", borderRadius: 16, padding: 28, maxWidth: 480, width: "90%", boxShadow: "0 20px 60px #0006" }}
              onClick={e => e.stopPropagation()}>
              <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 12 }}>{previewPrompt.name}</div>
              <div style={{ color: "var(--text-muted)", fontSize: 14, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{previewPrompt.text}</div>
              <button type="button" className="ghost-button" style={{ marginTop: 16, width: "100%" }} onClick={() => setPreviewPrompt(null)}>Закрити</button>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
