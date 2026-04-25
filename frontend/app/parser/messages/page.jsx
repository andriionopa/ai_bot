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
  message_limit: 1000,
  days_limit: 30,
  skip_bots: true,
  skip_deleted: true,
  skip_scam: true,
  only_with_username: false,
  only_with_photo: false,
  only_premium: false,
  only_active_users: false,
  include_forwards: true,
  include_replies: true,
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

export default function MessageParserPage() {
  const [overview, setOverview] = useState({ jobs: [], results: [], logs: [], accounts: [], channel_templates: [], templates: {} });
  const [form, setForm] = useState(defaultForm);
  const [selectedAccounts, setSelectedAccounts] = useState([]);
  const [selectedTemplateIds, setSelectedTemplateIds] = useState([]);
  const [sourceInput, setSourceInput] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [logLevel, setLogLevel] = useState("all");
  const [logSearch, setLogSearch] = useState("");
  const [resultSearch, setResultSearch] = useState("");
  const [sortBy, setSortBy] = useState("messages");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [selectedResultIds, setSelectedResultIds] = useState([]);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [userTemplateName, setUserTemplateName] = useState("");

  async function load() {
    try {
      const payload = await apiFetch("/api/v1/parser/messages/overview/");
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
      if (sortBy === "recent") return new Date(right.last_message_at || 0) - new Date(left.last_message_at || 0);
      if (sortBy === "name") return String(left.full_name || "").localeCompare(String(right.full_name || ""), "uk");
      return (right.message_count || 0) - (left.message_count || 0);
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

  function toggleResult(resultId) {
    setSelectedResultIds((prev) => prev.includes(resultId) ? prev.filter((id) => id !== resultId) : [...prev, resultId]);
  }

  function selectAllResults() {
    setSelectedResultIds(filteredResults.map((r) => r.id));
  }

  function clearSelectedResults() {
    setSelectedResultIds([]);
  }

  async function saveUserTemplate({ templateId = null, useAll = false } = {}) {
    setError("");
    setMessage("");
    if (!latestJob) { setError("Немає результатів для шаблону."); return; }
    if (!templateId && !userTemplateName.trim()) { setError("Вкажи назву шаблону."); return; }
    if (!useAll && !selectedResultIds.length) { setError("Оберіть хоча б один результат."); return; }
    try {
      const response = await apiFetch("/api/v1/parser/channels/channel-templates/attach-user-results/", {
        method: "POST",
        body: {
          template_id: templateId || undefined,
          name: templateId ? undefined : userTemplateName.trim(),
          job_id: latestJob.id,
          result_ids: useAll ? [] : selectedResultIds,
          select_all: useAll,
          parser_type: "messages",
        },
      });
      setUserTemplateName("");
      setSelectedResultIds([]);
      setMessage(`Шаблон «${response.template.name}»: додано ${response.added}, пропущено дублів ${response.skipped}.`);
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
  }

  async function deleteUserTemplate(templateId) {
    setError("");
    try {
      await apiFetch(`/api/v1/parser/channels/channel-templates/${templateId}/`, { method: "DELETE", body: {} });
      setMessage("Шаблон видалено.");
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
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

  async function createAndStart() {
    setError("");
    setMessage("");
    if (!selectedAccounts.length) {
      setError("Виберіть хоча б один акаунт для парсингу.");
      return;
    }
    const sources = Array.from(new Set([...(form.sources || []), ...templateSources()]));
    if (!sources.length) {
      setError("Додайте хоча б одне джерело або оберіть шаблон.");
      return;
    }
    try {
      const job = await apiFetch("/api/v1/parser/messages/jobs/add/", {
        method: "POST",
        body: {
          ...form,
          name: form.name || `Парсер по повідомленнях ${new Date().toLocaleString("uk-UA")}`,
          sources,
          account_ids: selectedAccounts,
          message_limit: Number(form.message_limit) || 1000,
          days_limit: Number(form.days_limit) || 30,
        },
      });
      await apiFetch(`/api/v1/parser/messages/jobs/${job.id}/start/`, { method: "POST", body: {} });
      setMessage("Парсер юзерів запущено.");
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
  }

  async function stopJob(jobId) {
    setError("");
    try {
      await apiFetch(`/api/v1/parser/messages/jobs/${jobId}/stop/`, { method: "POST", body: {} });
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
      const response = await apiFetch("/api/v1/parser/messages/results/clear/", { method: "POST", body: payload });
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
    const response = await fetch(backendApiUrl(`/api/v1/parser/messages/jobs/${latestJob.id}/export/?export_format=${format}`), {
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
    link.download = `message-parser-${latestJob.id}.${format}`;
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
            <h2>Парсер юзерів по повідомленнях</h2>
            <p>Збір користувачів із чатів та груп по історії повідомлень, навіть коли список учасників прихований.</p>
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
            <span>чати, ключові слова, фільтри</span>
          </div>

          <div className="warmup-card dashed-panel">
            <div className="section-title">
              <h4>ШІ захист</h4>
              <span>рандомні паузи в межах профілю</span>
            </div>
            <Toggle checked={form.ai_protection} onChange={(value) => patchForm("ai_protection", value)} label="AI захист акаунтів" note="Знижує ризик лімітів під час парсингу повідомлень." />
            <div className="pill-grid">
              {[
                ["safe", "Консервативний"],
                ["balanced", "Збалансований"],
                ["fast", "Агресивний"],
              ].map(([value, label]) => (
                <button key={value} type="button" className={`pill-button ${form.speed_mode === value ? "active" : ""}`} onClick={() => patchForm("speed_mode", value)}>
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="parser-input-row">
            <label>
              <span>Назва задачі</span>
              <input value={form.name} onChange={(event) => patchForm("name", event.target.value)} placeholder="Парсер по повідомленнях: товарка" />
            </label>
            <label>
              <span>Ліміт повідомлень</span>
              <input type="number" min="1" max="100000" value={form.message_limit} onChange={(event) => patchForm("message_limit", event.target.value)} />
            </label>
            <label>
              <span>Період, днів</span>
              <input type="number" min="0" max="365" value={form.days_limit} onChange={(event) => patchForm("days_limit", event.target.value)} />
            </label>
          </div>

          <div className="parser-input-row">
            <label style={{ gridColumn: "1 / -1" }}>
              <span>Список чатів</span>
              <textarea
                rows={5}
                value={sourceInput}
                onChange={(event) => setSourceInput(event.target.value)}
                placeholder="@channel&#10;https://t.me/chat&#10;-1001234567890"
              />
            </label>
          </div>
          <div className="parser-actions">
            <button type="button" className="ghost-button" onClick={addSources}>Додати джерела</button>
            <Toggle checked={form.fast_mode} onChange={(value) => patchForm("fast_mode", value)} label="Швидка робота" note="Для невеликих тестових чатів." />
          </div>
          <div className="parser-template-list">
            {(overview.channel_templates || []).map((template) => (
              <article key={template.id} className={`parser-template-card ${selectedTemplateIds.includes(template.id) ? "selected" : ""}`}>
                <b>{template.name}</b>
                <small>{template.item_count || 0} джерел із шаблону</small>
                <div className="parser-actions">
                  <button type="button" className={`ghost-button ${selectedTemplateIds.includes(template.id) ? "active" : ""}`} onClick={() => toggleTemplate(template.id)}>
                    {selectedTemplateIds.includes(template.id) ? "Обрано" : "Використати"}
                  </button>
                </div>
              </article>
            ))}
          </div>

          {!!form.sources.length && (
            <div className="parser-template-row">
              {form.sources.map((source) => (
                <button key={source} type="button" className="keyword-chip" onClick={() => removeSource(source)}>{source} ×</button>
              ))}
            </div>
          )}

          <div className="parser-input-row">
            <label style={{ gridColumn: "1 / -1" }}>
              <span>Ключові слова</span>
              <input value={keywordInput} onChange={(event) => setKeywordInput(event.target.value)} placeholder="розкрутити Telegram-канал, який криптогаманець обрати" />
            </label>
          </div>
          <div className="parser-actions">
            <button type="button" className="ghost-button" onClick={addKeywords}>Додати ключові слова</button>
            {Object.entries(overview.templates || {}).map(([name, words]) => (
              <button key={name} type="button" className="ghost-button" onClick={() => patchForm("keywords", Array.from(new Set([...(form.keywords || []), ...words])))}>
                {name}
              </button>
            ))}
          </div>
          {!!form.keywords.length && (
            <div className="parser-template-row">
              {form.keywords.map((word) => (
                <button key={word} type="button" className="keyword-chip" onClick={() => removeKeyword(word)}>{word} ×</button>
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
              <h4>Активність та опції</h4>
              <Toggle checked={form.only_active_users} onChange={(value) => patchForm("only_active_users", value)} label="Тільки активні користувачі" />
              <Toggle checked={form.include_replies} onChange={(value) => patchForm("include_replies", value)} label="Враховувати відповіді" />
              <Toggle checked={form.include_forwards} onChange={(value) => patchForm("include_forwards", value)} label="Враховувати переслані повідомлення" />
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
            <span>{filteredResults.length}{selectedResultIds.length ? ` · вибрано ${selectedResultIds.length}` : ""}</span>
          </div>
          <div className="parser-result-toolbar">
            <input value={resultSearch} onChange={(event) => setResultSearch(event.target.value)} placeholder="Пошук результатів..." />
            <select value={sortBy} onChange={(event) => setSortBy(event.target.value)}>
              <option value="messages">За кількістю повідомлень</option>
              <option value="recent">За останньою активністю</option>
              <option value="name">За іменем</option>
            </select>
            <button type="button" className="ghost-button" onClick={() => setTemplatesOpen(true)}>Шаблони</button>
            <button type="button" className="ghost-button" onClick={selectAllResults} disabled={!filteredResults.length}>Вибрати всі</button>
            <button type="button" className="ghost-button" onClick={clearSelectedResults} disabled={!selectedResultIds.length}>Зняти вибір</button>
            <button type="button" className="ghost-button danger" onClick={clearResults}>Очистити</button>
            <button type="button" className="ghost-button" onClick={copyLinks}>Скопіювати профілі</button>
            <button type="button" className="ghost-button" onClick={() => exportResults("csv")}>CSV</button>
            <button type="button" className="ghost-button" onClick={() => exportResults("json")}>JSON</button>
            <button type="button" className="ghost-button" onClick={() => exportResults("txt")}>TXT</button>
          </div>
          <div className="parser-results-list">
            {filteredResults.map((result) => (
              <article key={result.id} className={`parser-result-card ${selectedResultIds.includes(result.id) ? "selected" : ""}`}>
                <div>
                  <h4>{result.full_name || result.username || result.telegram_user_id}</h4>
                  <p>{result.username ? `@${result.username}` : "без username"} · {result.source_title || result.source_ref}</p>
                  <small>
                    повідомлень: {result.message_count} · перше: {formatDate(result.first_message_at)} · останнє: {formatDate(result.last_message_at)}
                  </small>
                  {!!result.matched_keywords?.length && <small>ключові слова: {result.matched_keywords.join(", ")}</small>}
                </div>
                <div className="parser-actions">
                  <button type="button" className="ghost-button" onClick={() => toggleResult(result.id)}>
                    {selectedResultIds.includes(result.id) ? "Зняти" : "Вибрати"}
                  </button>
                  {result.profile_url ? <a className="ghost-button" href={result.profile_url} target="_blank" rel="noreferrer">Відкрити</a> : null}
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>

      {templatesOpen && (
        <div className="modal-backdrop" onMouseDown={() => setTemplatesOpen(false)}>
          <div className="modal panel" onMouseDown={(e) => e.stopPropagation()}>
            <button type="button" className="modal-close ghost-button" onClick={() => setTemplatesOpen(false)}>×</button>
            <h2>Шаблони юзерів</h2>
            <div className="parser-input-row">
              <input value={userTemplateName} onChange={(e) => setUserTemplateName(e.target.value)} placeholder="Назва шаблону..." />
              <button type="button" onClick={() => saveUserTemplate()} disabled={!selectedResultIds.length}>Зберегти вибраних</button>
              <button type="button" className="ghost-button" onClick={() => saveUserTemplate({ useAll: true })} disabled={!filteredResults.length}>Всі результати</button>
            </div>
            <div className="parser-template-list">
              {(overview.channel_templates || []).length ? (overview.channel_templates || []).map((tpl) => (
                <article key={tpl.id} className="parser-template-card">
                  <div>
                    <b>{tpl.name}</b>
                    <small>{tpl.item_count || 0} юзерів</small>
                  </div>
                  <div className="parser-actions">
                    <button type="button" className="ghost-button" onClick={() => saveUserTemplate({ templateId: tpl.id })} disabled={!selectedResultIds.length}>Додати вибраних</button>
                    <button type="button" className="ghost-button danger" onClick={() => deleteUserTemplate(tpl.id)}>Видалити</button>
                  </div>
                </article>
              )) : <div className="empty-state">Шаблонів ще немає.</div>}
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
