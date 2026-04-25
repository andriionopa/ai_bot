"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AppShell from "@/components/AppShell";
import { apiFetch, normalizeApiError } from "@/lib/api";

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("uk-UA", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
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

const PARSER_TYPES = [
  { key: "channels", label: "Парсер каналів", endpoint: "/api/v1/parser/channels/jobs/" },
  { key: "messages", label: "Парсер по повідомленнях", endpoint: "/api/v1/parser/messages/jobs/" },
  { key: "comments", label: "Парсер коментарів", endpoint: "/api/v1/parser/comments/jobs/" },
];

const TYPE_ENDPOINT = Object.fromEntries(PARSER_TYPES.map((pt) => [pt.key, pt.endpoint]));

export default function ParserHistoryPage() {
  const [allJobs, setAllJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [filterType, setFilterType] = useState("all");
  const [filterStatus, setFilterStatus] = useState("all");
  const [search, setSearch] = useState("");
  const [deletingId, setDeletingId] = useState(null);

  const load = useCallback(async () => {
    try {
      const results = await Promise.all(
        PARSER_TYPES.map(async (pt) => {
          const data = await apiFetch(pt.endpoint);
          const jobs = Array.isArray(data) ? data : (data.results || []);
          return jobs.map((job) => ({ ...job, _type: pt.key, _typeLabel: pt.label }));
        })
      );
      setAllJobs(results.flat().sort((a, b) => new Date(b.created_at) - new Date(a.created_at)));
    } catch (exc) {
      if (exc instanceof Error && exc.message === "AUTH_REQUIRED") {
        window.location.replace("/auth");
        return;
      }
      setError(normalizeApiError(exc));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return allJobs.filter((job) => {
      if (filterType !== "all" && job._type !== filterType) return false;
      if (filterStatus !== "all" && job.status !== filterStatus) return false;
      if (q && !`${job.name} ${job._typeLabel}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [allJobs, filterType, filterStatus, search]);

  const counts = useMemo(() => {
    const c = { all: allJobs.length };
    for (const job of allJobs) {
      c[job._type] = (c[job._type] || 0) + 1;
      c[job.status] = (c[job.status] || 0) + 1;
    }
    return c;
  }, [allJobs]);

  async function deleteJob(job) {
    setError("");
    setMessage("");
    setDeletingId(`${job._type}-${job.id}`);
    try {
      await apiFetch(`${TYPE_ENDPOINT[job._type]}${job.id}/`, { method: "DELETE", body: {} });
      setAllJobs((prev) => prev.filter((j) => !(j._type === job._type && j.id === job.id)));
      setMessage("Задачу видалено.");
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setDeletingId(null);
    }
  }

  async function clearFiltered() {
    setError("");
    setMessage("");
    const toDelete = filtered.filter((j) => j.status !== "running");
    if (!toDelete.length) { setError("Немає задач для очищення (активні не видаляються)."); return; }
    try {
      await Promise.all(
        toDelete.map((job) =>
          apiFetch(`${TYPE_ENDPOINT[job._type]}${job.id}/`, { method: "DELETE", body: {} })
        )
      );
      const deletedKeys = new Set(toDelete.map((j) => `${j._type}-${j.id}`));
      setAllJobs((prev) => prev.filter((j) => !deletedKeys.has(`${j._type}-${j.id}`)));
      setMessage(`Видалено ${toDelete.length} задач.`);
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
  }

  return (
    <AppShell userLabel="operator">
      <div className="settings-shell parser-page">
        <section className="hero-card parser-hero">
          <div>
            <h2>Історія парсингу</h2>
            <p>Всі задачі парсингу: канали, повідомлення та коментарі.</p>
          </div>
          <div className="parser-run-card">
            <small>Всього задач</small>
            <b>{allJobs.length}</b>
            <span>{allJobs.filter((j) => j.status === "running").length} активних</span>
          </div>
        </section>

        {(error || message) && (
          <section className={`dashed-panel ${error ? "danger-soft" : "success-soft"}`}>
            <b>{error ? "Помилка" : "Готово"}</b>
            <div>{error || message}</div>
          </section>
        )}

        <section className="warmup-card dashed-panel">
          <div className="parser-result-toolbar" style={{ flexWrap: "wrap" }}>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Пошук за назвою..."
              style={{ minWidth: 200 }}
            />
            <select value={filterType} onChange={(e) => setFilterType(e.target.value)}>
              <option value="all">Всі типи ({counts.all || 0})</option>
              {PARSER_TYPES.map((pt) => (
                <option key={pt.key} value={pt.key}>{pt.label} ({counts[pt.key] || 0})</option>
              ))}
            </select>
            <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
              <option value="all">Всі статуси</option>
              <option value="running">В роботі ({counts.running || 0})</option>
              <option value="succeeded">Завершено ({counts.succeeded || 0})</option>
              <option value="stopped">Зупинено ({counts.stopped || 0})</option>
              <option value="failed">Помилка ({counts.failed || 0})</option>
              <option value="draft">Чернетка ({counts.draft || 0})</option>
            </select>
            <button
              type="button"
              className="ghost-button danger"
              onClick={clearFiltered}
              disabled={!filtered.filter((j) => j.status !== "running").length}
            >
              Очистити показані ({filtered.filter((j) => j.status !== "running").length})
            </button>
          </div>

          {loading ? (
            <div style={{ padding: "32px 0", textAlign: "center", color: "var(--muted)" }}>Завантаження...</div>
          ) : filtered.length === 0 ? (
            <div style={{ padding: "32px 0", textAlign: "center", color: "var(--muted)" }}>
              {allJobs.length === 0 ? "Ще не було жодного парсингу." : "Нічого не знайдено."}
            </div>
          ) : (
            <div className="parser-results-list" style={{ marginTop: 12 }}>
              {filtered.map((job) => {
                const key = `${job._type}-${job.id}`;
                return (
                  <article key={key} className="parser-result-card">
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <h4 style={{ margin: "0 0 4px" }}>{job.name || `#${job.id}`}</h4>
                      <p style={{ margin: "0 0 4px", fontSize: 13, color: "var(--muted)" }}>{job._typeLabel}</p>
                      <small>
                        Запущено: {formatDate(job.created_at)}
                        {job.finished_at ? ` · Завершено: ${formatDate(job.finished_at)}` : ""}
                        {job.result_count != null ? ` · Результатів: ${job.result_count}` : ""}
                      </small>
                      {job.error ? (
                        <small style={{ color: "var(--red)", display: "block", marginTop: 4 }}>
                          {job.error.slice(0, 120)}
                        </small>
                      ) : null}
                    </div>
                    <div className="parser-actions" style={{ alignItems: "center", gap: 8 }}>
                      <span
                        className={`terminal-line ${statusClass(job.status)}`}
                        style={{ padding: "4px 10px", borderRadius: 8, fontSize: 13, border: "1px solid transparent" }}
                      >
                        {statusLabel(job.status)}
                      </span>
                      {job.status !== "running" && (
                        <button
                          type="button"
                          className="ghost-button danger"
                          disabled={deletingId === key}
                          onClick={() => deleteJob(job)}
                        >
                          {deletingId === key ? "..." : "Видалити"}
                        </button>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </AppShell>
  );
}
