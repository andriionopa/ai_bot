"use client";

import { useEffect, useMemo, useState } from "react";
import AppShell from "@/components/AppShell";
import { apiFetch, normalizeApiError } from "@/lib/api";

const HARDCODED_EMOJIS = ["👍", "❤", "🔥", "😁", "🤔", "👏", "🙏", "🎉"];

const defaultForm = {
  name: "",
  sources: [],
  emojis: [...HARDCODED_EMOJIS],
  emoji_mode: "random",
  reaction_probability: 1.0,
  work_mode: "existing",
  post_limit: 20,
  max_reactions: 0,
  duration_minutes: 60,
  reaction_delay_min: 3,
  reaction_delay_max: 10,
  entry_delay_min: 0,
  entry_delay_max: 5,
  ai_protection: true,
  speed_mode: "balanced",
  use_channel_identity: false,
  account_rotation: true,
  use_subscriptions: false,
  subscriptions_limit: 50,
  ai_smart_emoji: false,
  react_to_comments: false,
  comment_reaction_probability: 0.3,
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

function formatDate(value) {
  if (!value) return "немає";
  return new Date(value).toLocaleString("uk-UA", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function statusLabel(status) {
  if (status === "running") return "В роботі";
  if (status === "succeeded") return "Завершено";
  if (status === "failed") return "Помилка";
  if (status === "stopped") return "Зупинено";
  return "Чернетка";
}

function statusClass(status) {
  if (status === "running") return "info";
  if (status === "succeeded") return "success";
  if (status === "failed") return "error";
  if (status === "stopped") return "warning";
  return "";
}

function normalizeListInput(value) {
  return String(value || "")
    .split(/[,;\n\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function ReactionsPage() {
  const [overview, setOverview] = useState({
    jobs: [], logs: [], accounts: [], bindings: [], channel_templates: [], hardcoded_emojis: HARDCODED_EMOJIS,
  });
  const [form, setForm] = useState(defaultForm);
  const [selectedAccounts, setSelectedAccounts] = useState([]);
  const [selectedTemplateIds, setSelectedTemplateIds] = useState([]);
  const [sourceInput, setSourceInput] = useState("");
  const [logSearch, setLogSearch] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  // Binding modal
  const [bindingOpen, setBindingOpen] = useState(false);
  const [bindingAccountId, setBindingAccountId] = useState("");
  const [bindingChannel, setBindingChannel] = useState("");
  const [bindingTitle, setBindingTitle] = useState("");
  const [savingBinding, setSavingBinding] = useState(false);

  async function load() {
    try {
      const payload = await apiFetch("/api/v1/reactions/overview/");
      setOverview(payload);
      if (!selectedAccounts.length && payload.accounts?.length) {
        setSelectedAccounts([payload.accounts[0].id]);
      }
    } catch (exc) {
      if (exc instanceof Error && exc.message === "AUTH_REQUIRED") {
        window.location.replace("/auth");
        return;
      }
      setError(normalizeApiError(exc));
    }
  }

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);

  const latestJob = overview.jobs?.[0] || null;
  const isRunning = latestJob?.status === "running";

  const filteredLogs = useMemo(() => {
    const q = logSearch.trim().toLowerCase();
    return (overview.logs || []).filter((log) =>
      !q || `${log.message} ${log.account_label || ""}`.toLowerCase().includes(q)
    );
  }, [overview.logs, logSearch]);

  function patchForm(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function toggleAccount(id) {
    setSelectedAccounts((prev) => (prev.includes(id) ? prev.filter((a) => a !== id) : [...prev, id]));
  }

  function addSources() {
    const items = normalizeListInput(sourceInput);
    if (!items.length) return;
    setForm((prev) => ({ ...prev, sources: Array.from(new Set([...(prev.sources || []), ...items])) }));
    setSourceInput("");
  }

  function removeSource(source) {
    setForm((prev) => ({ ...prev, sources: (prev.sources || []).filter((s) => s !== source) }));
  }

  function toggleTemplate(templateId) {
    setSelectedTemplateIds((prev) => (prev.includes(templateId) ? prev.filter((id) => id !== templateId) : [...prev, templateId]));
  }

  function templateSources() {
    const sources = [];
    for (const template of overview.channel_templates || []) {
      if (!selectedTemplateIds.includes(template.id)) continue;
      for (const item of template.items || []) {
        const source = item.url || (item.username ? `@${item.username}` : item.telegram_id);
        if (source) sources.push(String(source));
      }
    }
    return Array.from(new Set(sources));
  }

  function toggleEmoji(emoji) {
    const current = form.emojis || [];
    if (current.includes(emoji)) {
      if (current.length === 1) return;
      patchForm("emojis", current.filter((e) => e !== emoji));
    } else {
      patchForm("emojis", [...current, emoji]);
    }
  }

  async function createAndStart() {
    setError("");
    setMessage("");
    if (!selectedAccounts.length) { setError("Виберіть хоча б один акаунт."); return; }
    if (!form.name.trim()) { setError("Вкажіть назву задачі."); return; }
    const sources = Array.from(new Set([...(form.sources || []), ...templateSources()]));
    if (!sources.length && !form.use_subscriptions) { setError("Додайте джерело, оберіть шаблон або увімкніть підписки."); return; }

    try {
      const job = await apiFetch("/api/v1/reactions/jobs/", {
        method: "POST",
        body: { ...form, sources, accounts: selectedAccounts },
      });
      await apiFetch(`/api/v1/reactions/jobs/${job.id}/start/`, { method: "POST", body: {} });
      setMessage("Задачу запущено.");
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
  }

  async function stopJob() {
    if (!latestJob) return;
    setError("");
    try {
      await apiFetch(`/api/v1/reactions/jobs/${latestJob.id}/stop/`, { method: "POST", body: {} });
      setMessage("Задачу зупинено.");
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
  }

  async function saveBinding() {
    if (!bindingAccountId || !bindingChannel.trim()) return;
    setSavingBinding(true);
    setError("");
    try {
      await apiFetch("/api/v1/reactions/bindings/", {
        method: "POST",
        body: {
          account: bindingAccountId,
          channel_username: bindingChannel.trim().replace(/^@/, ""),
          title: bindingTitle.trim() || bindingChannel.trim(),
        },
      });
      setBindingOpen(false);
      setBindingChannel("");
      setBindingTitle("");
      setBindingAccountId("");
      setMessage("Прив'язку збережено.");
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setSavingBinding(false);
    }
  }

  async function deleteBinding(id) {
    setError("");
    try {
      await apiFetch(`/api/v1/reactions/bindings/${id}/`, { method: "DELETE", body: {} });
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
  }

  const reactionProgress = latestJob && latestJob.max_reactions > 0
    ? Math.min(100, Math.round(((latestJob.reactions_sent ?? 0) / latestJob.max_reactions) * 100))
    : null;

  return (
    <AppShell userLabel="operator">
      <div className="settings-shell parser-page">
        {/* Hero */}
        <section className="hero-card parser-hero">
          <div>
            <h2>Масові реакції</h2>
            <p>Автоматичне відправлення реакцій у Telegram-канали.</p>
          </div>
          <div className="parser-run-card">
            <small>Всього задач</small>
            <b>{overview.jobs?.length || 0}</b>
            <span>{(overview.jobs || []).filter((j) => j.status === "running").length} активних</span>
          </div>
        </section>

        {(error || message) && (
          <section className={`dashed-panel ${error ? "danger-soft" : "success-soft"}`}>
            <b>{error ? "Помилка" : "Готово"}</b>
            <div>{error || message}</div>
          </section>
        )}

        <div className="parser-two-col">
          {/* LEFT: Config */}
          <div className="parser-config-col">

            {/* Назва */}
            <section className="warmup-card dashed-panel">
              <h4>Назва задачі</h4>
              <input
                value={form.name}
                onChange={(e) => patchForm("name", e.target.value)}
                placeholder="Наприклад: Реакції на crypto_ua"
              />
            </section>

            {/* Акаунти */}
            <section className="warmup-card dashed-panel">
              <h4>Акаунти</h4>
              {!(overview.accounts || []).length ? (
                <p style={{ color: "var(--muted)" }}>Немає підключених акаунтів.</p>
              ) : (
                <div className="parser-account-picker">
                  {(overview.accounts || []).map((acc) => (
                    <button
                      key={acc.id}
                      type="button"
                      className={`account-chip ${selectedAccounts.includes(acc.id) ? "selected" : ""}`}
                      onClick={() => toggleAccount(acc.id)}
                    >
                      <span className={`dot ${acc.auth_state === "connected" ? "green" : "red"}`} />
                      {acc.label}
                      {acc.is_reacting ? <span style={{ fontSize: 10, color: "var(--yellow)", marginLeft: 4 }}>реакції</span> : null}
                    </button>
                  ))}
                </div>
              )}
              <Toggle
                checked={form.account_rotation}
                onChange={(v) => patchForm("account_rotation", v)}
                label="Ротація акаунтів"
                note="Чергувати акаунти між каналами"
              />
            </section>

            {/* Джерела */}
            <section className="warmup-card dashed-panel">
              <h4>Канали для реакцій</h4>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  value={sourceInput}
                  onChange={(e) => setSourceInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addSources()}
                  placeholder="@username або https://t.me/..."
                  style={{ flex: 1 }}
                />
                <button type="button" className="ghost-button" onClick={addSources}>Додати</button>
              </div>
              {(form.sources || []).length > 0 && (
                <div className="source-chips" style={{ marginTop: 8 }}>
                  {(form.sources || []).map((source) => (
                    <span key={source} className="source-chip">
                      {source}
                      <button type="button" onClick={() => removeSource(source)}>×</button>
                    </span>
                  ))}
                </div>
              )}

              {/* Шаблони каналів */}
              {(overview.channel_templates || []).length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <small style={{ color: "var(--muted)" }}>Або оберіть шаблон каналів:</small>
                  <div className="parser-template-list" style={{ marginTop: 6 }}>
                    {(overview.channel_templates || []).map((tpl) => (
                      <button
                        key={tpl.id}
                        type="button"
                        className={`parser-template-chip ${selectedTemplateIds.includes(tpl.id) ? "selected" : ""}`}
                        onClick={() => toggleTemplate(tpl.id)}
                      >
                        {selectedTemplateIds.includes(tpl.id) ? "✓ " : ""}{tpl.name}
                        <span style={{ opacity: 0.6, marginLeft: 4, fontSize: 11 }}>({tpl.item_count || 0})</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {/* Підписки */}
              <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
                <Toggle
                  checked={form.use_subscriptions}
                  onChange={(v) => patchForm("use_subscriptions", v)}
                  label="Реагувати в каналах із підписок"
                  note="Акаунт сам підбере канали/групи зі своїх підписок"
                />
                {form.use_subscriptions && (
                  <div className="parser-field-row" style={{ marginTop: 8 }}>
                    <label>
                      <span>Кількість каналів із підписок</span>
                      <input
                        type="number"
                        min={1}
                        max={500}
                        value={form.subscriptions_limit}
                        onChange={(e) => patchForm("subscriptions_limit", Number(e.target.value))}
                        style={{ width: 80 }}
                      />
                    </label>
                  </div>
                )}
              </div>
            </section>

            {/* Emoji */}
            <section className="warmup-card dashed-panel">
              <h4>Реакції (емодзі)</h4>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
                {HARDCODED_EMOJIS.map((emoji) => (
                  <button
                    key={emoji}
                    type="button"
                    onClick={() => toggleEmoji(emoji)}
                    style={{
                      fontSize: 22,
                      padding: "6px 10px",
                      borderRadius: 10,
                      border: "2px solid",
                      borderColor: (form.emojis || []).includes(emoji) ? "var(--accent)" : "var(--border)",
                      background: (form.emojis || []).includes(emoji) ? "var(--accent-soft)" : "transparent",
                      cursor: "pointer",
                      transition: "all 0.15s",
                    }}
                    title={(form.emojis || []).includes(emoji) ? "Прибрати" : "Додати"}
                  >
                    {emoji}
                  </button>
                ))}
              </div>
              <div className="pill-grid" style={{ marginBottom: 6 }}>
                {[{ key: "random", label: "Випадковий" }, { key: "sequential", label: "По черзі" }].map(({ key, label }) => (
                  <button
                    key={key}
                    type="button"
                    className={`pill-button ${form.emoji_mode === key ? "active" : ""}`}
                    onClick={() => patchForm("emoji_mode", key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <small style={{ color: "var(--muted)" }}>Режим вибору емодзі для кожного поста</small>
            </section>

            {/* Режим роботи */}
            <section className="warmup-card dashed-panel">
              <h4>Режим роботи</h4>
              <div className="pill-grid" style={{ marginBottom: 10 }}>
                {[{ key: "existing", label: "Існуючі пости" }, { key: "monitoring", label: "Моніторинг нових" }].map(({ key, label }) => (
                  <button
                    key={key}
                    type="button"
                    className={`pill-button ${form.work_mode === key ? "active" : ""}`}
                    onClick={() => patchForm("work_mode", key)}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {form.work_mode === "existing" && (
                <div className="parser-field-row">
                  <label>
                    <span>Постів на канал</span>
                    <input
                      type="number"
                      min={1}
                      max={500}
                      value={form.post_limit}
                      onChange={(e) => patchForm("post_limit", Number(e.target.value))}
                    />
                  </label>
                </div>
              )}
              {form.work_mode === "monitoring" && (
                <div className="parser-field-row">
                  <label>
                    <span>Тривалість (хв)</span>
                    <input
                      type="number"
                      min={1}
                      max={1440}
                      value={form.duration_minutes}
                      onChange={(e) => patchForm("duration_minutes", Number(e.target.value))}
                    />
                  </label>
                </div>
              )}
              <div className="parser-field-row">
                <label>
                  <span>Макс. реакцій (0 = без ліміту)</span>
                  <input
                    type="number"
                    min={0}
                    value={form.max_reactions}
                    onChange={(e) => patchForm("max_reactions", Number(e.target.value))}
                  />
                </label>
              </div>
              <div className="parser-field-row">
                <label>
                  <span>Вірогідність реакції (%)</span>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={Math.round(form.reaction_probability * 100)}
                    onChange={(e) => patchForm("reaction_probability", Number(e.target.value) / 100)}
                  />
                  <b style={{ minWidth: 36, textAlign: "right" }}>{Math.round(form.reaction_probability * 100)}%</b>
                </label>
              </div>
            </section>

            {/* Затримки */}
            <section className="warmup-card dashed-panel">
              <h4>Затримки</h4>
              <div className="parser-field-row">
                <span>Між реакціями (сек)</span>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="number"
                    min={0}
                    step={0.5}
                    value={form.reaction_delay_min}
                    onChange={(e) => patchForm("reaction_delay_min", Number(e.target.value))}
                    style={{ width: 70 }}
                    placeholder="Від"
                  />
                  <span style={{ color: "var(--muted)" }}>–</span>
                  <input
                    type="number"
                    min={0}
                    step={0.5}
                    value={form.reaction_delay_max}
                    onChange={(e) => patchForm("reaction_delay_max", Number(e.target.value))}
                    style={{ width: 70 }}
                    placeholder="До"
                  />
                </div>
              </div>
              <div className="parser-field-row" style={{ marginTop: 8 }}>
                <span>Стартова затримка (сек)</span>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="number"
                    min={0}
                    step={0.5}
                    value={form.entry_delay_min}
                    onChange={(e) => patchForm("entry_delay_min", Number(e.target.value))}
                    style={{ width: 70 }}
                    placeholder="Від"
                  />
                  <span style={{ color: "var(--muted)" }}>–</span>
                  <input
                    type="number"
                    min={0}
                    step={0.5}
                    value={form.entry_delay_max}
                    onChange={(e) => patchForm("entry_delay_max", Number(e.target.value))}
                    style={{ width: 70 }}
                    placeholder="До"
                  />
                </div>
              </div>
            </section>

            {/* AI захист */}
            <section className="warmup-card dashed-panel">
              <div className="section-title" style={{ marginBottom: 8 }}>
                <span className="section-icon green">🛡</span>
                <div><h4 style={{ margin: 0 }}>ШІ захист від блокувань</h4></div>
                <div style={{ marginLeft: "auto" }}>
                  <Toggle checked={form.ai_protection} onChange={(v) => patchForm("ai_protection", v)} label="" />
                </div>
              </div>
              {form.ai_protection && (
                <div className="pill-grid" style={{ marginTop: 10 }}>
                  {[
                    { key: "safe", label: "Консервативний" },
                    { key: "balanced", label: "Збалансований" },
                    { key: "fast", label: "Агресивний" },
                  ].map(({ key, label }) => (
                    <button
                      key={key}
                      type="button"
                      className={`pill-button ${form.speed_mode === key ? "active" : ""}`}
                      onClick={() => patchForm("speed_mode", key)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
            </section>

            {/* Premium: реакції від імені каналу */}
            <section className="warmup-card dashed-panel">
              <Toggle
                checked={form.use_channel_identity}
                onChange={(v) => patchForm("use_channel_identity", v)}
                label="Реакції від імені каналу (Premium)"
                note="Потрібен Premium-акаунт і прив'язка каналу до акаунту"
              />
              {form.use_channel_identity && (
                <div style={{ marginTop: 10 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                    <small style={{ color: "var(--muted)" }}>Прив'язки акаунт → канал</small>
                    <button type="button" className="ghost-button" onClick={() => setBindingOpen(true)}>+ Додати</button>
                  </div>
                  {!(overview.bindings || []).length ? (
                    <p style={{ color: "var(--muted)", fontSize: 13 }}>Немає прив'язок. Додайте через кнопку вище.</p>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {(overview.bindings || []).map((b) => (
                        <div key={b.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 10px", background: "var(--bg-card)", borderRadius: 8, border: "1px solid var(--border)" }}>
                          <span style={{ fontSize: 13 }}>
                            <b>{b.account_label}</b> → @{b.channel_username}
                            {b.title ? <span style={{ color: "var(--muted)", marginLeft: 4 }}>({b.title})</span> : null}
                          </span>
                          <button type="button" className="ghost-button danger" onClick={() => deleteBinding(b.id)}>×</button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </section>

            {/* ШІ + реакції на коментарі */}
            <section className="warmup-card dashed-panel">
              <h4>Додаткові реакції</h4>
              <Toggle
                checked={form.ai_smart_emoji}
                onChange={(v) => patchForm("ai_smart_emoji", v)}
                label="ШІ обирає реакцію"
                note="Аналізує текст поста/коментаря і ставить найбільш підходящий emoji"
              />
              <div style={{ marginTop: 10 }}>
                <Toggle
                  checked={form.react_to_comments}
                  onChange={(v) => patchForm("react_to_comments", v)}
                  label="Реагувати на коментарів"
                  note="Ставити реакції на коментарі у discussion-групах каналів"
                />
              </div>
              {form.react_to_comments && (
                <div className="parser-field-row" style={{ marginTop: 10 }}>
                  <label>
                    <span>Ймовірність реакції на коментар (%)</span>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={Math.round(form.comment_reaction_probability * 100)}
                      onChange={(e) => patchForm("comment_reaction_probability", Number(e.target.value) / 100)}
                    />
                    <b style={{ minWidth: 36, textAlign: "right" }}>{Math.round(form.comment_reaction_probability * 100)}%</b>
                  </label>
                </div>
              )}
            </section>

            {/* Launch */}
            <section className="warmup-card dashed-panel">
              {isRunning ? (
                <button type="button" className="ghost-button danger" style={{ width: "100%" }} onClick={stopJob}>
                  Зупинити
                </button>
              ) : (
                <button type="button" className="ghost-button" style={{ width: "100%" }} onClick={createAndStart}>
                  Запустити реакції
                </button>
              )}
            </section>
          </div>

          {/* RIGHT: Status + Logs */}
          <div className="parser-results-col">

            {/* Status card */}
            {latestJob && (
              <section className="warmup-card dashed-panel">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div>
                    <h4 style={{ margin: "0 0 4px" }}>{latestJob.name}</h4>
                    <small style={{ color: "var(--muted)" }}>
                      Запуск: {formatDate(latestJob.started_at)}
                      {latestJob.finished_at ? ` · Завершено: ${formatDate(latestJob.finished_at)}` : ""}
                    </small>
                  </div>
                  <span
                    className={`terminal-line ${statusClass(latestJob.status)}`}
                    style={{ padding: "4px 10px", borderRadius: 8, fontSize: 13, border: "1px solid transparent" }}
                  >
                    {statusLabel(latestJob.status)}
                  </span>
                </div>

                {/* Reactions counter */}
                <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: 28, fontWeight: 700, color: "var(--accent)" }}>{latestJob.reactions_sent ?? 0}</div>
                    <small style={{ color: "var(--muted)" }}>реакцій відправлено</small>
                  </div>
                  {reactionProgress !== null && (
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                        <small style={{ color: "var(--muted)" }}>Прогрес</small>
                        <small>{reactionProgress}%</small>
                      </div>
                      <div style={{ height: 6, background: "var(--border)", borderRadius: 4, overflow: "hidden" }}>
                        <div style={{ height: "100%", width: `${reactionProgress}%`, background: "var(--accent)", borderRadius: 4, transition: "width 0.4s" }} />
                      </div>
                    </div>
                  )}
                </div>

                {latestJob.error ? (
                  <div style={{ marginTop: 10, color: "var(--red)", fontSize: 13 }}>{latestJob.error}</div>
                ) : null}
              </section>
            )}

            {/* History */}
            {(overview.jobs || []).length > 1 && (
              <section className="warmup-card dashed-panel">
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                  <h4 style={{ margin: 0 }}>Історія</h4>
                  <button
                    type="button"
                    className="ghost-button danger"
                    style={{ fontSize: 12, padding: "3px 10px" }}
                    onClick={async () => {
                      if (!confirm("Видалити всі завершені/зупинені завдання?")) return;
                      await apiFetch("/api/v1/reactions/jobs/clear_finished/", { method: "DELETE", body: {} });
                      loadOverview();
                    }}
                  >
                    Очистити
                  </button>
                </div>
                <div className="parser-results-list">
                  {(overview.jobs || []).slice(1).map((job) => (
                    <article key={job.id} className="parser-result-card" style={{ padding: "8px 12px" }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <h4 style={{ margin: "0 0 2px", fontSize: 14 }}>{job.name}</h4>
                        <small style={{ color: "var(--muted)" }}>
                          {formatDate(job.created_at)} · Реакцій: {job.reactions_sent ?? 0}
                        </small>
                      </div>
                      <span
                        className={`terminal-line ${statusClass(job.status)}`}
                        style={{ padding: "3px 8px", borderRadius: 6, fontSize: 12, border: "1px solid transparent" }}
                      >
                        {statusLabel(job.status)}
                      </span>
                    </article>
                  ))}
                </div>
              </section>
            )}

            {/* Logs */}
            <section className="warmup-card logs-card">
              <div className="log-toolbar">
                <span className="online-dot">● в мережі</span>
                <span>Усі {filteredLogs.length}</span>
                <span>Успіх {filteredLogs.filter((l) => l.level === "success" || l.level === "info").length}</span>
                <span>Помилки {filteredLogs.filter((l) => l.level === "error").length}</span>
                <input
                  value={logSearch}
                  onChange={(e) => setLogSearch(e.target.value)}
                  placeholder="Пошук..."
                  style={{ marginLeft: "auto", width: 140 }}
                />
              </div>
              <div className="terminal">
                {filteredLogs.length === 0 && (
                  <div className="empty-state">Логів поки немає</div>
                )}
                {[...filteredLogs].reverse().map((log) => (
                  <div key={log.id} className={`terminal-line ${log.level}`}>
                    <time>{new Date(log.created_at).toLocaleTimeString("uk-UA")}</time>
                    <span>{log.level === "error" ? "❌" : log.level === "warning" ? "⚠️" : "✅"}</span>
                    <b>{log.account_label || "system"}</b>
                    <p>{log.message}</p>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      </div>

      {/* Binding modal */}
      {bindingOpen && (
        <div className="modal-overlay" onClick={() => setBindingOpen(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <h3>Прив'язати канал до акаунту</h3>
            <p style={{ color: "var(--muted)", fontSize: 13 }}>
              Для реакцій від імені каналу (Premium): вкажіть який канал адмініструє цей акаунт.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
              <div>
                <label style={{ fontSize: 13, color: "var(--muted)" }}>Акаунт</label>
                <select
                  value={bindingAccountId}
                  onChange={(e) => setBindingAccountId(e.target.value)}
                  style={{ width: "100%", marginTop: 4 }}
                >
                  <option value="">Оберіть акаунт...</option>
                  {(overview.accounts || []).map((acc) => (
                    <option key={acc.id} value={acc.id}>{acc.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label style={{ fontSize: 13, color: "var(--muted)" }}>Username каналу</label>
                <input
                  value={bindingChannel}
                  onChange={(e) => setBindingChannel(e.target.value)}
                  placeholder="@channel або channel"
                  style={{ width: "100%", marginTop: 4 }}
                />
              </div>
              <div>
                <label style={{ fontSize: 13, color: "var(--muted)" }}>Назва (опційно)</label>
                <input
                  value={bindingTitle}
                  onChange={(e) => setBindingTitle(e.target.value)}
                  placeholder="Мій канал"
                  style={{ width: "100%", marginTop: 4 }}
                />
              </div>
            </div>
            <div style={{ display: "flex", gap: 10, marginTop: 16, justifyContent: "flex-end" }}>
              <button type="button" className="ghost-button" onClick={() => setBindingOpen(false)}>Скасувати</button>
              <button
                type="button"
                className="ghost-button"
                disabled={savingBinding || !bindingAccountId || !bindingChannel.trim()}
                onClick={saveBinding}
              >
                {savingBinding ? "..." : "Зберегти"}
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
