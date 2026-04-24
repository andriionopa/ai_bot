"use client";

import { useEffect, useMemo, useState } from "react";
import AppShell from "@/components/AppShell";
import { apiFetch, authTokens, backendApiUrl, normalizeApiError } from "@/lib/api";

const defaultForm = {
  name: "",
  keywords: [],
  sources: [],
  ai_protection: true,
  fast_mode: false,
  speed_mode: "balanced",
  post_limit: 50,
  comment_limit: 200,
  days_limit: 30,
  skip_bots: true,
  skip_deleted: true,
  skip_scam: true,
  only_with_username: false,
  only_with_photo: false,
  only_premium: false,
  only_active_users: false,
};

function Toggle({ checked, onChange, label, note }) {
  return (
    <label className="toggle-line parser-toggle">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span className="switch" />
      <span>
        <b>{label}</b>
        {note ? <small>{note}</small> : null}
      </span>
    </label>
  );
}

function normalizeListInput(value) {
  return String(value || "")
    .split(/[,;\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatDate(value) {
  if (!value) return "немає";
  return new Date(value).toLocaleString("uk-UA", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function CommentParserPage() {
  const [overview, setOverview] = useState({ jobs: [], results: [], logs: [], accounts: [], templates: {} });
  const [form, setForm] = useState(defaultForm);
  const [selectedAccounts, setSelectedAccounts] = useState([]);
  const [sourceInput, setSourceInput] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [logLevel, setLogLevel] = useState("all");
  const [logSearch, setLogSearch] = useState("");
  const [resultSearch, setResultSearch] = useState("");
  const [sortBy, setSortBy] = useState("comments");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function load() {
    try {
      const payload = await apiFetch("/api/v1/parser/comments/overview/");
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

  const filteredLogs = useMemo(() => {
    const query = logSearch.trim().toLowerCase();
    return (overview.logs || []).filter((log) => {
      if (logLevel !== "all" && log.level !== logLevel) return false;
      return !query || `${log.message} ${log.account_label || ""}`.toLowerCase().includes(query);
    });
  }, [overview.logs, logLevel, logSearch]);

  const filteredResults = useMemo(() => {
    const query = resultSearch.trim().toLowerCase();
    const items = (overview.results || []).filter((result) => {
      if (!query) return true;
      return `${result.full_name} ${result.username} ${result.source_title} ${result.profile_url}`.toLowerCase().includes(query);
    });
    return [...items].sort((left, right) => {
      if (sortBy === "recent") return new Date(right.last_comment_at || 0) - new Date(left.last_comment_at || 0);
      if (sortBy === "name") return String(left.full_name || "").localeCompare(String(right.full_name || ""), "uk");
      return (right.comment_count || 0) - (left.comment_count || 0);
    });
  }, [overview.results, resultSearch, sortBy]);

  function patchForm(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function toggleAccount(accountId) {
    setSelectedAccounts((prev) => (prev.includes(accountId) ? prev.filter((id) => id !== accountId) : [...prev, accountId]));
  }

  function addKeywords() {
    const words = normalizeListInput(keywordInput);
    if (!words.length) return;
    setForm((prev) => ({ ...prev, keywords: Array.from(new Set([...(prev.keywords || []), ...words])) }));
    setKeywordInput("");
  }

  function removeKeyword(word) {
    setForm((prev) => ({ ...prev, keywords: (prev.keywords || []).filter((item) => item !== word) }));
  }

  function addSources() {
    const items = normalizeListInput(sourceInput);
    if (!items.length) return;
    setForm((prev) => ({ ...prev, sources: Array.from(new Set([...(prev.sources || []), ...items])) }));
    setSourceInput("");
  }

  function removeSource(source) {
    setForm((prev) => ({ ...prev, sources: (prev.sources || []).filter((item) => item !== source) }));
  }

  async function createAndStart() {
    setError("");
    setMessage("");
    if (!selectedAccounts.length) {
      setError("Виберіть хоча б один акаунт для парсингу.");
      return;
    }
    if (!(form.sources || []).length) {
      setError("Додайте хоча б одне джерело.");
      return;
    }
    try {
      const job = await apiFetch("/api/v1/parser/comments/jobs/add/", {
        method: "POST",
        body: {
          ...form,
          name: form.name || `Парсер коментарів ${new Date().toLocaleString("uk-UA")}`,
          account_ids: selectedAccounts,
          post_limit: Number(form.post_limit) || 50,
          comment_limit: Number(form.comment_limit) || 200,
          days_limit: Number(form.days_limit) || 30,
        },
      });
      await apiFetch(`/api/v1/parser/comments/jobs/${job.id}/start/`, { method: "POST", body: {} });
      setMessage("Парсер коментарів запущено.");
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
  }

  async function stopJob(jobId) {
    setError("");
    try {
      await apiFetch(`/api/v1/parser/comments/jobs/${jobId}/stop/`, { method: "POST", body: {} });
      setMessage("Парсинг зупинено.");
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
  }

  async function clearResults() {
    setError("");
    try {
      const payload = latestJob ? { job_id: latestJob.id } : {};
      const response = await apiFetch("/api/v1/parser/comments/results/clear/", { method: "POST", body: payload });
      setMessage(`Очищено результатів: ${response.deleted || 0}.`);
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
  }

  async function copyLinks() {
    const text = filteredResults
      .map((item) => item.profile_url || (item.username ? `@${item.username}` : item.telegram_user_id))
      .filter(Boolean)
      .join("\n");
    await navigator.clipboard.writeText(text);
    setMessage(`Скопійовано профілів: ${text ? text.split("\n").length : 0}.`);
  }

  async function exportResults(format) {
    if (!latestJob) return;
    const { access } = authTokens();
    const response = await fetch(backendApiUrl(`/api/v1/parser/comments/jobs/${latestJob.id}/export/?export_format=${format}`), {
      headers: access ? { Authorization: `Bearer ${access}` } : {},
      credentials: "include",
    });
    if (!response.ok) {
      setError(`Експорт не виконано: HTTP ${response.status}`);
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `comment-parser-${latestJob.id}.${format}`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const logCounters = useMemo(() => {
    const counters = { all: overview.logs?.length || 0, info: 0, success: 0, warning: 0, error: 0, debug: 0 };
    for (const log of overview.logs || []) counters[log.level] = (counters[log.level] || 0) + 1;
    return counters;
  }, [overview.logs]);

  return (
    <AppShell userLabel="operator">
      <div className="settings-shell parser-page">
        <section className="hero-card parser-hero">
          <div>
            <h2>Парсер коментарів</h2>
            <p>
              Збір активних коментаторів із відкритих каналів. Якщо коментарі в каналі закриті — джерело
              буде пропущено з відповідним повідомленням в логах.
            </p>
          </div>
          <div className="parser-run-card">
            <small>Останній запуск</small>
            <b>{latestJob ? latestJob.name : "ще не було"}</b>
            <span>{latestJob ? formatDate(latestJob.created_at) : "—"}</span>
          </div>
        </section>

        {(message || error) ? (
          <section className={`dashed-panel ${error ? "danger-soft" : "success-soft"}`}>
            <b>{error ? "Помилка" : "Готово"}</b>
            <div>{error || message}</div>
          </section>
        ) : null}

        <section className="warmup-card dashed-panel">
          <div className="section-title">
            <h3>Вибір акаунтів</h3>
            <span>{selectedAccounts.length} вибрано</span>
          </div>
          <div className="account-picker parser-account-picker">
            {(overview.accounts || []).map((account) => (
              <button
                key={account.id}
                type="button"
                className={selectedAccounts.includes(account.id) ? "selected" : ""}
                onClick={() => toggleAccount(account.id)}
              >
                <span>{account.label}</span>
                <small>{account.phone_number || account.telegram_username || "без номера"}</small>
              </button>
            ))}
          </div>
        </section>

        <section className="warmup-card dashed-panel">
          <div className="section-title">
            <h3>Налаштування парсингу</h3>
            <span>канали, ключові слова, фільтри</span>
          </div>

          <div className="warmup-card dashed-panel">
            <div className="section-title">
              <h4>ШІ захист</h4>
              <span>рандомні паузи в межах профілю</span>
            </div>
            <Toggle
              checked={form.ai_protection}
              onChange={(value) => patchForm("ai_protection", value)}
              label="AI захист акаунтів"
              note="Знижує ризик лімітів під час парсингу коментарів."
            />
            <div className="pill-grid">
              {[
                ["safe", "Консервативний"],
                ["balanced", "Збалансований"],
                ["fast", "Агресивний"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={`pill-button ${form.speed_mode === value ? "active" : ""}`}
                  onClick={() => patchForm("speed_mode", value)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="parser-input-row">
            <label>
              <span>Назва задачі</span>
              <input
                value={form.name}
                onChange={(event) => patchForm("name", event.target.value)}
                placeholder="Парсер коментарів: крипта"
              />
            </label>
            <label>
              <span>Постів на канал</span>
              <input
                type="number"
                min="1"
                max="10000"
                value={form.post_limit}
                onChange={(event) => patchForm("post_limit", event.target.value)}
              />
            </label>
            <label>
              <span>Коментарів на пост</span>
              <input
                type="number"
                min="1"
                max="5000"
                value={form.comment_limit}
                onChange={(event) => patchForm("comment_limit", event.target.value)}
              />
            </label>
            <label>
              <span>Період, днів</span>
              <input
                type="number"
                min="0"
                max="365"
                value={form.days_limit}
                onChange={(event) => patchForm("days_limit", event.target.value)}
              />
            </label>
          </div>

          <div className="parser-input-row">
            <label style={{ gridColumn: "1 / -1" }}>
              <span>Список каналів</span>
              <textarea
                rows={5}
                value={sourceInput}
                onChange={(event) => setSourceInput(event.target.value)}
                placeholder="@channel&#10;https://t.me/channel&#10;-1001234567890"
              />
            </label>
          </div>
          <div className="parser-actions">
            <button type="button" className="ghost-button" onClick={addSources}>Додати джерела</button>
            <Toggle
              checked={form.fast_mode}
              onChange={(value) => patchForm("fast_mode", value)}
              label="Швидка робота"
              note="Для невеликих тестових каналів."
            />
          </div>

          {!!form.sources.length && (
            <div className="parser-template-row">
              {form.sources.map((source) => (
                <button key={source} type="button" className="keyword-chip" onClick={() => removeSource(source)}>
                  {source} ×
                </button>
              ))}
            </div>
          )}

          <div className="parser-input-row">
            <label style={{ gridColumn: "1 / -1" }}>
              <span>Ключові слова</span>
              <input
                value={keywordInput}
                onChange={(event) => setKeywordInput(event.target.value)}
                placeholder="крипта, airdrop, купити"
              />
            </label>
          </div>
          <div className="parser-actions">
            <button type="button" className="ghost-button" onClick={addKeywords}>Додати ключові слова</button>
            {Object.entries(overview.templates || {}).map(([name, words]) => (
              <button
                key={name}
                type="button"
                className="ghost-button"
                onClick={() => patchForm("keywords", Array.from(new Set([...(form.keywords || []), ...words])))}
              >
                {name}
              </button>
            ))}
          </div>
          {!!form.keywords.length && (
            <div className="parser-template-row">
              {form.keywords.map((word) => (
                <button key={word} type="button" className="keyword-chip" onClick={() => removeKeyword(word)}>
                  {word} ×
                </button>
              ))}
            </div>
          )}

          <div className="parser-input-row">
            <div className="warmup-card dashed-panel">
              <h4>Базові фільтри</h4>
              <Toggle checked={form.skip_bots} onChange={(value) => patchForm("skip_bots", value)} label="Пропустити ботів" />
              <Toggle checked={form.skip_deleted} onChange={(value) => patchForm("skip_deleted", value)} label="Пропустити видалених" />
              <Toggle checked={form.skip_scam} onChange={(value) => patchForm("skip_scam", value)} label="Пропустити заблокованих/scam" />
            </div>
            <div className="warmup-card dashed-panel">
              <h4>Фільтри профілю</h4>
              <Toggle checked={form.only_with_username} onChange={(value) => patchForm("only_with_username", value)} label="Тільки з username" />
              <Toggle checked={form.only_with_photo} onChange={(value) => patchForm("only_with_photo", value)} label="Тільки з фото" />
              <Toggle checked={form.only_premium} onChange={(value) => patchForm("only_premium", value)} label="Тільки Premium" />
            </div>
            <div className="warmup-card dashed-panel">
              <h4>Активність</h4>
              <Toggle
                checked={form.only_active_users}
                onChange={(value) => patchForm("only_active_users", value)}
                label="Тільки активні"
                note="Мінімум 2 коментарі у каналі."
              />
            </div>
          </div>
        </section>

        <section className="warmup-card launch-panel">
          <div>
            <h3>Запуск парсингу</h3>
            <small>{latestJob ? `${latestJob.name} · ${latestJob.status}` : "ще немає активної задачі"}</small>
          </div>
          <div className="parser-actions">
            <button type="button" className="primary-button" onClick={createAndStart}>Почати</button>
            {latestJob?.status === "running" ? (
              <button type="button" className="ghost-button" onClick={() => stopJob(latestJob.id)}>Зупинити</button>
            ) : null}
          </div>
        </section>

        <section className="warmup-card dashed-panel">
          <div className="section-title">
            <h3>Логи</h3>
            <span>{logCounters.all} записів</span>
          </div>
          <div className="log-toolbar">
            {["all", "info", "success", "warning", "error", "debug"].map((level) => (
              <button key={level} type="button" className={logLevel === level ? "active" : ""} onClick={() => setLogLevel(level)}>
                {level} {logCounters[level] || 0}
              </button>
            ))}
            <input value={logSearch} onChange={(event) => setLogSearch(event.target.value)} placeholder="Пошук логів..." />
          </div>
          <div className="terminal parser-terminal">
            {filteredLogs.map((log) => (
              <div key={log.id} className={`terminal-line ${log.level}`}>
                <span>{formatDate(log.created_at)}</span>
                <b>{log.account_label || "system"}</b>
                <span>{log.message}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="warmup-card dashed-panel">
          <div className="section-title">
            <h3>Результати парсингу</h3>
            <span>{filteredResults.length}</span>
          </div>
          <div className="parser-result-toolbar">
            <input
              value={resultSearch}
              onChange={(event) => setResultSearch(event.target.value)}
              placeholder="Пошук результатів..."
            />
            <select value={sortBy} onChange={(event) => setSortBy(event.target.value)}>
              <option value="comments">За кількістю коментарів</option>
              <option value="recent">За останньою активністю</option>
              <option value="name">За іменем</option>
            </select>
            <button type="button" className="ghost-button" onClick={clearResults}>Очистити</button>
            <button type="button" className="ghost-button" onClick={copyLinks}>Скопіювати профілі</button>
            <button type="button" className="ghost-button" onClick={() => exportResults("csv")}>CSV</button>
            <button type="button" className="ghost-button" onClick={() => exportResults("json")}>JSON</button>
            <button type="button" className="ghost-button" onClick={() => exportResults("txt")}>TXT</button>
          </div>
          <div className="parser-results-list">
            {filteredResults.map((result) => (
              <article key={result.id} className="parser-result-card">
                <div>
                  <h4>{result.full_name || result.username || result.telegram_user_id}</h4>
                  <p>
                    {result.username ? `@${result.username}` : "без username"} · {result.source_title || result.source_ref}
                  </p>
                  <small>
                    коментарів: {result.comment_count} · перший: {formatDate(result.first_comment_at)} · останній: {formatDate(result.last_comment_at)}
                  </small>
                  {!!result.matched_keywords?.length && (
                    <small>ключові слова: {result.matched_keywords.join(", ")}</small>
                  )}
                  {result.sample_comment && (
                    <small style={{ fontStyle: "italic", opacity: 0.7 }}>«{result.sample_comment.slice(0, 120)}»</small>
                  )}
                </div>
                <div className="parser-actions">
                  {result.profile_url ? (
                    <a className="ghost-button" href={result.profile_url} target="_blank" rel="noreferrer">Відкрити</a>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>
    </AppShell>
  );
}
