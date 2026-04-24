"use client";

import { useEffect, useMemo, useState } from "react";
import AppShell from "@/components/AppShell";
import { apiFetch, authTokens, backendApiUrl, normalizeApiError } from "@/lib/api";

const defaultForm = {
  name: "",
  keywords: ["Бізнес", "Заробіток", "Бізнес Telegram", "Бізнес ідеї"],
  suffixes: ["2025", "2026"],
  parse_type: "channels",
  search_scope: "both",
  ai_protection: true,
  fast_mode: false,
  speed_mode: "balanced",
  activity_filter: "any",
  comments_filter: "any",
  result_limit: 50,
  subscriber_min: 500,
  subscriber_max: 1000000,
  rating_min: 5,
  language_detection: true,
  languages: ["uk", "ru", "en"],
  request_delay_seconds: 2,
  channel_delay_seconds: 1,
};

const languageOptions = [
  ["uk", "Українська"],
  ["ru", "Російська"],
  ["en", "Англійська"],
  ["be", "Білоруська"],
  ["tr", "Турецька"],
  ["de", "Німецька"],
  ["fr", "Французька"],
  ["es", "Іспанська"],
  ["it", "Італійська"],
  ["pt", "Португальська"],
];

const resultLimitOptions = [10, 25, 50, 100, 200, 500];

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
    .map((item) => item.trim().replace(/\s+/g, " "))
    .filter(Boolean);
}

function formatDate(value) {
  if (!value) return "немає";
  return new Date(value).toLocaleString("uk-UA", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function statusLabel(status) {
  if (status === "running") return "В роботі";
  if (status === "succeeded") return "Завершено";
  if (status === "failed") return "Помилка";
  if (status === "stopped") return "Зупинено";
  return "Чернетка";
}

function Modal({ title, onClose, children }) {
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal panel" onMouseDown={(event) => event.stopPropagation()}>
        <button type="button" className="modal-close ghost-button" onClick={onClose}>×</button>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export default function ChannelParserPage() {
  const [overview, setOverview] = useState({ jobs: [], results: [], logs: [], accounts: [], templates: {}, parser_templates: [], channel_templates: [] });
  const [form, setForm] = useState(defaultForm);
  const [selectedAccounts, setSelectedAccounts] = useState([]);
  const [keywordInput, setKeywordInput] = useState("");
  const [suffixInput, setSuffixInput] = useState("");
  const [channelTemplateName, setChannelTemplateName] = useState("");
  const [selectedResultIds, setSelectedResultIds] = useState([]);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [logLevel, setLogLevel] = useState("all");
  const [logSearch, setLogSearch] = useState("");
  const [resultSearch, setResultSearch] = useState("");
  const [sortBy, setSortBy] = useState("rating");
  const [resultTypeFilter, setResultTypeFilter] = useState("all");
  const [resultActivityFilter, setResultActivityFilter] = useState("all");
  const [resultCommentsFilter, setResultCommentsFilter] = useState("all");
  const [resultLanguageFilter, setResultLanguageFilter] = useState("all");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function load() {
    try {
      const payload = await apiFetch("/api/v1/parser/channels/overview/");
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
  const runningJob = (overview.jobs || []).find((job) => job.status === "running");

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
      if (resultTypeFilter !== "all" && result.entity_type !== resultTypeFilter) return false;
      if (resultActivityFilter !== "all" && result.activity_level !== resultActivityFilter) return false;
      if (resultCommentsFilter === "open" && !result.comments_open) return false;
      if (resultCommentsFilter === "closed" && result.comments_open) return false;
      if (resultLanguageFilter !== "all" && (result.language || "") !== resultLanguageFilter) return false;
      if (!query) return true;
      return `${result.title} ${result.username} ${result.url}`.toLowerCase().includes(query);
    });
    return [...items].sort((left, right) => {
      if (sortBy === "subscribers") return (right.subscribers || 0) - (left.subscribers || 0);
      if (sortBy === "created") return new Date(right.created_at) - new Date(left.created_at);
      return (right.rating || 0) - (left.rating || 0);
    });
  }, [overview.results, resultSearch, sortBy, resultTypeFilter, resultActivityFilter, resultCommentsFilter, resultLanguageFilter]);

  const logCounters = useMemo(() => {
    const counters = { all: overview.logs?.length || 0, info: 0, success: 0, warning: 0, error: 0, debug: 0 };
    for (const log of overview.logs || []) counters[log.level] = (counters[log.level] || 0) + 1;
    return counters;
  }, [overview.logs]);

  function patchForm(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function addWords(field, value, reset) {
    const words = normalizeListInput(value);
    if (!words.length) return;
    setForm((prev) => ({ ...prev, [field]: Array.from(new Set([...(prev[field] || []), ...words])) }));
    reset("");
  }

  function removeWord(field, word) {
    setForm((prev) => ({ ...prev, [field]: (prev[field] || []).filter((item) => item !== word) }));
  }

  function applyTemplate(name) {
    const words = overview.templates?.[name] || [];
    setForm((prev) => ({ ...prev, keywords: Array.from(new Set([...(prev.keywords || []), ...words])) }));
  }

  function toggleLanguage(code) {
    setForm((prev) => {
      const current = new Set(prev.languages || []);
      if (current.has(code)) current.delete(code);
      else current.add(code);
      return { ...prev, languages: Array.from(current) };
    });
  }

  function toggleResult(resultId) {
    setSelectedResultIds((prev) => (prev.includes(resultId) ? prev.filter((id) => id !== resultId) : [...prev, resultId]));
  }

  function selectAllResults() {
    setSelectedResultIds(filteredResults.map((item) => item.id));
  }

  function clearSelectedResults() {
    setSelectedResultIds([]);
  }

  async function saveChannelTemplate({ templateId = null, useAll = false } = {}) {
    setError("");
    setMessage("");
    if (!latestJob) {
      setError("Немає результатів для шаблону каналів.");
      return;
    }
    if (!templateId && !channelTemplateName.trim()) {
      setError("Вкажи назву шаблону каналів.");
      return;
    }
    if (!useAll && !selectedResultIds.length) {
      setError("Оберіть хоча б один канал із результатів.");
      return;
    }
    try {
      const response = await apiFetch("/api/v1/parser/channels/channel-templates/attach-results/", {
        method: "POST",
        body: {
          template_id: templateId || undefined,
          name: templateId ? undefined : channelTemplateName.trim(),
          job_id: latestJob.id,
          result_ids: useAll ? [] : selectedResultIds,
          select_all: useAll,
        },
      });
      setChannelTemplateName("");
      setSelectedResultIds([]);
      setMessage(`Шаблон «${response.template.name}»: додано ${response.added}, пропущено дублів ${response.skipped}.`);
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
  }

  async function deleteChannelTemplate(templateId) {
    setError("");
    try {
      await apiFetch(`/api/v1/parser/channels/channel-templates/${templateId}/`, { method: "DELETE", body: {} });
      setMessage("Шаблон каналів видалено.");
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
  }

  async function clearResults() {
    setError("");
    try {
      const payload = latestJob ? { job_id: latestJob.id } : {};
      const response = await apiFetch("/api/v1/parser/channels/results/clear/", { method: "POST", body: payload });
      setMessage(`Очищено результатів: ${response.deleted || 0}.`);
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
  }

  async function createAndStart() {
    setError("");
    setMessage("");
    if (!selectedAccounts.length) {
      setError("Виберіть хоча б один акаунт для парсингу.");
      return;
    }
    try {
      const job = await apiFetch("/api/v1/parser/channels/jobs/add/", {
        method: "POST",
        body: {
          ...form,
          name: form.name || `Парсинг даних ${new Date().toLocaleString("uk-UA")}`,
          account_ids: selectedAccounts,
          subscriber_min: Number(form.subscriber_min) || 0,
          subscriber_max: Number(form.subscriber_max) || 0,
          rating_min: Number(form.rating_min) || 0,
          result_limit: Number(form.result_limit) || 50,
          request_delay_seconds: Number(form.request_delay_seconds) || 0,
          channel_delay_seconds: Number(form.channel_delay_seconds) || 0,
        },
      });
      await apiFetch(`/api/v1/parser/channels/jobs/${job.id}/start/`, { method: "POST", body: {} });
      setMessage("Парсинг даних запущено.");
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
  }

  async function stopJob(jobId) {
    setError("");
    try {
      await apiFetch(`/api/v1/parser/channels/jobs/${jobId}/stop/`, { method: "POST", body: {} });
      setMessage("Парсинг зупинено.");
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
  }

  async function copyLinks() {
    const links = filteredResults.map((item) => item.url).filter(Boolean).join("\n");
    await navigator.clipboard.writeText(links);
    setMessage(`Скопійовано посилань: ${links ? links.split("\n").length : 0}.`);
  }

  async function exportResults(format) {
    if (!latestJob) return;
    const { access } = authTokens();
    const response = await fetch(backendApiUrl(`/api/v1/parser/channels/jobs/${latestJob.id}/export/?export_format=${format}`), {
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
    link.download = `channel-parser-${latestJob.id}.${format}`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <AppShell>
      <div className="settings-shell parser-page">
        <section className="hero-card parser-hero">
          <div>
            <div className="eyebrow">data parsing</div>
            <h2>Парсинг даних</h2>
            <p>Пошук Telegram-каналів або груп по ключових словах, фільтрах, GEO та активності.</p>
          </div>
          <div className="parser-run-card">
            <span>{latestJob ? statusLabel(latestJob.status) : "Готовий"}</span>
            <b>{overview.results?.length || 0}</b>
            <small>результатів у поточній базі</small>
          </div>
        </section>

        {(error || message) && (
          <section className={`dashed-panel ${error ? "danger-soft" : "success-soft"}`}>
            {error || message}
          </section>
        )}

        <section className="warmup-card dashed-panel">
          <div className="section-title">
            <span className="section-icon">♙</span>
            <div>
              <h3>Вибір акаунтів</h3>
              <p>{selectedAccounts.length} вибрано з {overview.accounts?.length || 0}</p>
            </div>
          </div>
          <div className="parser-actions">
            <button type="button" className="ghost-button" onClick={() => setSelectedAccounts((overview.accounts || []).map((account) => account.id))}>Додати всі</button>
            <button type="button" className="ghost-button danger" onClick={() => setSelectedAccounts([])}>Очистити</button>
          </div>
          <div className="account-picker parser-account-picker">
            {(overview.accounts || []).map((account) => {
              const active = selectedAccounts.includes(account.id);
              return (
                <button
                  key={account.id}
                  type="button"
                  className={active ? "active" : ""}
                  onClick={() =>
                    setSelectedAccounts((prev) => active ? prev.filter((id) => id !== account.id) : [...prev, account.id])
                  }
                >
                  <b>{account.label}</b>
                  <small>{account.username ? `@${account.username}` : account.phone_number || "connected"}</small>
                  <span>{account.status} · {account.role_label || "резерв"}</span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="warmup-grid two">
          <div className="warmup-card dashed-panel">
            <div className="section-title">
              <span className="section-icon">⌕</span>
              <div>
                <h3>Ключові слова</h3>
                <p>{form.keywords.length} слів, {form.suffixes.length} закінчень</p>
              </div>
            </div>

            <label>
              Назва задачі
              <input value={form.name} onChange={(event) => patchForm("name", event.target.value)} placeholder="Парсинг даних: товарка" />
            </label>

            <label>
              Тип парсингу
              <div className="segmented-grid">
                {[
                  ["channels", "Канали"],
                  ["groups", "Групи"],
                ].map(([value, label]) => (
                  <button key={value} type="button" className={form.parse_type === value ? "active" : ""} onClick={() => patchForm("parse_type", value)}>
                    {label}
                  </button>
                ))}
              </div>
            </label>

            <div className="parser-input-row">
              <input value={keywordInput} onChange={(event) => setKeywordInput(event.target.value)} placeholder="Слова через кому..." />
              <button type="button" onClick={() => addWords("keywords", keywordInput, setKeywordInput)}>Додати</button>
            </div>
            <div className="chip-row">
              {form.keywords.map((word) => (
                <button key={word} type="button" className="keyword-chip" onClick={() => removeWord("keywords", word)}>{word} ×</button>
              ))}
            </div>
            <div className="parser-template-row">
              {Object.keys(overview.templates || {}).map((template) => (
                <button key={template} type="button" className="ghost-button" onClick={() => applyTemplate(template)}>{template}</button>
              ))}
            </div>

            <div className="parser-input-row">
              <input value={suffixInput} onChange={(event) => setSuffixInput(event.target.value)} placeholder="Закінчення: 2025, 2026..." />
              <button type="button" onClick={() => addWords("suffixes", suffixInput, setSuffixInput)}>Додати</button>
            </div>
            <div className="chip-row">
              {form.suffixes.map((word) => (
                <button key={word} type="button" className="suffix-chip" onClick={() => removeWord("suffixes", word)}>{word} ×</button>
              ))}
            </div>
          </div>

          <div className="warmup-card dashed-panel">
            <div className="section-title">
              <span className="section-icon">▣</span>
              <div>
                <h3>Режим і ліміти</h3>
                <p>Жорсткі межі для Telegram API</p>
              </div>
            </div>
            <Toggle checked={form.ai_protection} onChange={(value) => patchForm("ai_protection", value)} label="ШІ-захист акаунтів" note="Рандомізує паузи між діями і знижує паливність" />

            <label>
              Джерело пошуку
              <div className="segmented-grid">
                {[
                  ["global", "Telegram"],
                  ["subscriptions", "Підписки"],
                  ["both", "Обидва"],
                ].map(([value, label]) => (
                  <button key={value} type="button" className={form.search_scope === value ? "active" : ""} onClick={() => patchForm("search_scope", value)}>
                    {label}
                  </button>
                ))}
              </div>
            </label>

            <div className="segmented-grid">
              {[
                ["safe", "Консервативний"],
                ["balanced", "Збалансований"],
                ["fast", "Агресивний"],
              ].map(([mode, label]) => (
                <button key={mode} type="button" className={form.speed_mode === mode ? "active" : ""} onClick={() => patchForm("speed_mode", mode)}>
                  {label}
                </button>
              ))}
            </div>

            <label>
              Ліміт результатів
              <div className="segmented-grid limit-grid">
                {resultLimitOptions.map((limit) => (
                  <button key={limit} type="button" className={Number(form.result_limit) === limit ? "active" : ""} onClick={() => patchForm("result_limit", limit)}>
                    {limit}
                  </button>
                ))}
              </div>
            </label>
          </div>
        </section>

        <section className="warmup-card dashed-panel">
          <div className="section-title">
            <span className="section-icon">☷</span>
            <div>
              <h3>Фільтри</h3>
              <p>Активність, коментарі, підписники, рейтинг і GEO</p>
            </div>
          </div>

          <div className="warmup-grid two">
            <div>
              <h4>Активність</h4>
              <div className="segmented-grid">
                {[["any", "Будь-які"], ["active", "Тільки активні"], ["inactive", "Неактивні"]].map(([value, label]) => (
                  <button key={value} type="button" className={form.activity_filter === value ? "active" : ""} onClick={() => patchForm("activity_filter", value)}>{label}</button>
                ))}
              </div>
            </div>
            <div>
              <h4>Коментарі</h4>
              <div className="segmented-grid">
                {[["any", "Будь-які"], ["open", "Відкриті"], ["closed", "Закриті"]].map(([value, label]) => (
                  <button key={value} type="button" className={form.comments_filter === value ? "active" : ""} onClick={() => patchForm("comments_filter", value)}>{label}</button>
                ))}
              </div>
            </div>
          </div>

          <div className="field-row four">
            <label>Мін. підписників<input type="number" min="0" value={form.subscriber_min} onChange={(event) => patchForm("subscriber_min", event.target.value)} /></label>
            <label>Макс. підписників<input type="number" min="0" value={form.subscriber_max} onChange={(event) => patchForm("subscriber_max", event.target.value)} /></label>
            <label>Рейтинг<input type="number" min="0" max="10" value={form.rating_min} onChange={(event) => patchForm("rating_min", event.target.value)} /></label>
            <Toggle checked={form.language_detection} onChange={(value) => patchForm("language_detection", value)} label="Визначення GEO" />
          </div>

          <div className="language-grid">
            {languageOptions.map(([code, label]) => (
              <label key={code} className="checkbox-line">
                <input type="checkbox" checked={(form.languages || []).includes(code)} onChange={() => toggleLanguage(code)} disabled={!form.language_detection} />
                {label}
              </label>
            ))}
          </div>
        </section>

        <section className="warmup-card launch-panel">
          <div className="launch-box">
            <div>
              <h3>Запуск парсингу</h3>
              <p>{runningJob ? `Активна задача: ${runningJob.name}` : "Готово до збору бази каналів"}</p>
            </div>
            <div className="parser-actions">
              <button type="button" onClick={createAndStart} disabled={Boolean(runningJob)}>Запустити парсинг</button>
              {runningJob ? <button type="button" className="ghost-button danger" onClick={() => stopJob(runningJob.id)}>Зупинити</button> : null}
            </div>
          </div>
        </section>

        <section className="warmup-card logs-card">
          <div className="log-toolbar">
            <b><span className="state-dot">•</span> Логи</b>
            {["all", "info", "success", "warning", "error"].map((level) => (
              <button key={level} type="button" className={logLevel === level ? "active" : ""} onClick={() => setLogLevel(level)}>
                {level === "all" ? "всі" : level} {logCounters[level] || 0}
              </button>
            ))}
            <input value={logSearch} onChange={(event) => setLogSearch(event.target.value)} placeholder="Пошук логів..." />
          </div>
          <div className="terminal parser-terminal">
            {filteredLogs.length ? filteredLogs.map((log) => (
              <div key={log.id} className={`terminal-line ${log.level}`}>
                <span>{formatDate(log.created_at)}</span>
                <span>{log.level === "success" ? "✓" : log.level === "error" ? "×" : log.level === "warning" ? "!" : "i"}</span>
                <b>{log.account_label || "parser"}</b>
                <p>{log.message}</p>
              </div>
            )) : <div className="empty-state">Логів ще немає.</div>}
          </div>
        </section>

        <section className="warmup-card dashed-panel">
          <div className="section-title">
            <span className="section-icon">▤</span>
            <div>
              <h3>Результати пошуку</h3>
              <p>Показано {filteredResults.length} з {overview.results?.length || 0}</p>
            </div>
          </div>
          <div className="parser-result-toolbar">
            <input value={resultSearch} onChange={(event) => setResultSearch(event.target.value)} placeholder="Пошук результатів..." />
            <select value={resultTypeFilter} onChange={(event) => setResultTypeFilter(event.target.value)}>
              <option value="all">Усі типи</option>
              <option value="channel">Канали</option>
              <option value="group">Групи</option>
            </select>
            <select value={resultActivityFilter} onChange={(event) => setResultActivityFilter(event.target.value)}>
              <option value="all">Будь-яка активність</option>
              <option value="active">Активні</option>
              <option value="inactive">Неактивні</option>
            </select>
            <select value={resultCommentsFilter} onChange={(event) => setResultCommentsFilter(event.target.value)}>
              <option value="all">Будь-які коментарі</option>
              <option value="open">Відкриті</option>
              <option value="closed">Закриті</option>
            </select>
            <select value={resultLanguageFilter} onChange={(event) => setResultLanguageFilter(event.target.value)}>
              <option value="all">Усі GEO</option>
              {languageOptions.map(([code, label]) => (
                <option key={code} value={code}>{label}</option>
              ))}
            </select>
            <select value={sortBy} onChange={(event) => setSortBy(event.target.value)}>
              <option value="rating">За рейтингом</option>
              <option value="subscribers">За підписниками</option>
              <option value="created">Нові спочатку</option>
            </select>
            <button type="button" className="ghost-button" onClick={() => setTemplatesOpen(true)}>Шаблони</button>
            <button type="button" className="ghost-button" onClick={selectAllResults} disabled={!filteredResults.length}>Вибрати всі</button>
            <button type="button" className="ghost-button" onClick={clearSelectedResults} disabled={!selectedResultIds.length}>Очистити вибір</button>
            <button type="button" className="ghost-button danger" onClick={clearResults}>Очистити</button>
            <button type="button" className="ghost-button" onClick={copyLinks}>Скопіювати посилання</button>
            <button type="button" onClick={() => exportResults("csv")} disabled={!latestJob}>CSV</button>
            <button type="button" onClick={() => exportResults("json")} disabled={!latestJob}>JSON</button>
            <button type="button" onClick={() => exportResults("txt")} disabled={!latestJob}>TXT</button>
          </div>

          <div className="parser-results-list">
            {filteredResults.length ? filteredResults.map((result) => (
              <article key={result.id} className={`parser-result-card ${selectedResultIds.includes(result.id) ? "selected" : ""}`}>
                <div className="section-icon">▤</div>
                <div>
                  <h4>{result.title}</h4>
                  <p>{result.username ? `@${result.username}` : result.telegram_id} · {result.entity_type === "group" ? "група" : "канал"} · {Number(result.subscribers || 0).toLocaleString("uk-UA")} підписників</p>
                  <small>rating {result.rating}/10 · {result.activity_level || "unknown"} · {result.comments_open ? "коментарі відкриті" : "коментарі закриті"} · {result.language || "geo n/a"}</small>
                </div>
                <div className="parser-actions">
                  <button type="button" className="ghost-button" onClick={() => toggleResult(result.id)}>
                    {selectedResultIds.includes(result.id) ? "Зняти" : "Вибрати"}
                  </button>
                  <a className="ghost-button" href={result.url || "#"} target="_blank" rel="noreferrer">Відкрити</a>
                </div>
              </article>
            )) : <div className="empty-state">Результатів ще немає.</div>}
          </div>
        </section>
      </div>
      {templatesOpen ? (
        <Modal title="Шаблони каналів" onClose={() => setTemplatesOpen(false)}>
          <div className="parser-input-row">
            <input value={channelTemplateName} onChange={(event) => setChannelTemplateName(event.target.value)} placeholder="Назва шаблону каналів..." />
            <button type="button" onClick={() => saveChannelTemplate()}>Створити з вибраних</button>
            <button type="button" className="ghost-button" onClick={() => saveChannelTemplate({ useAll: true })} disabled={!filteredResults.length}>Усі з результатів</button>
          </div>
          <div className="parser-template-list">
            {(overview.channel_templates || []).length ? (overview.channel_templates || []).map((template) => (
              <article key={template.id} className="parser-template-card">
                <div>
                  <b>{template.name}</b>
                  <small>{template.item_count || 0} каналів{template.items?.length ? ` · ${(template.items || []).slice(0, 3).map((item) => item.title).join(", ")}` : ""}</small>
                </div>
                <div className="parser-actions">
                  <button type="button" className="ghost-button" onClick={() => saveChannelTemplate({ templateId: template.id })} disabled={!selectedResultIds.length}>Додати вибрані</button>
                  <button type="button" className="ghost-button danger" onClick={() => deleteChannelTemplate(template.id)}>Видалити</button>
                </div>
              </article>
            )) : <div className="empty-state">Шаблонів ще немає.</div>}
          </div>
        </Modal>
      ) : null}
    </AppShell>
  );
}
