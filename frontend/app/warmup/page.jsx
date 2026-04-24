"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import { apiFetch, normalizeApiError } from "@/lib/api";

const defaultPolicy = {
  name: "Людська активність 1-2 дні",
  behavior_profile: "balanced",
  daily_join_min: 3,
  daily_join_max: 8,
  delay_min_seconds: 120,
  delay_max_seconds: 480,
  read_min_seconds: 20,
  read_max_seconds: 90,
  reaction_probability: 25,
  max_reactions_per_day: 18,
  retry_min_seconds: 300,
  retry_max_seconds: 900,
  active_start_hour: 9,
  active_end_hour: 23,
  actions_per_hour: 12,
  actions_per_day: 120,
  messages_per_day: 8,
  session_duration_minutes: 1440,
  random_breaks: true,
  auto_adapt_limits: true,
  progressive_ramp: true,
  allow_folder_one_click: true,
  allow_public_gradual_join: true,
  allow_private_join: true,
  warmup_source: "subscriptions",
  enable_reactions: true,
  enable_read_channels: true,
  enable_account_dialogs: false,
  enable_story_view: true,
  enable_join_groups: true,
  enable_trust_boost: true,
  enable_view_dialogs: true,
  enable_channel_scroll: true,
  enable_mark_read: true,
  enable_message_search: true,
  enable_forward_messages: true,
  enable_saved_notes: true,
  enable_poll_scan: true,
  enable_video_scan: true,
  enable_voice_scan: true,
  enable_gif_search: true,
  enable_sticker_scan: true,
  enable_inline_bot_check: true,
  enable_link_preview: true,
  enable_typing_simulation: true,
  enable_profile_view: true,
  enable_settings_check: true,
  enable_gradual_profile_check: true,
  enable_emoji_status_check: true,
  enable_drafts_check: true,
  enable_notification_check: true,
  enable_scheduled_message_check: true,
  enable_archive_check: true,
  enable_mute_check: true,
  search_query: "",
  inline_bot_username: "gif",
  is_active: true,
};

const actionGroups = [
  ["Основні дії", [["enable_reactions", "Реакції 👍 ❤️ 🔥"], ["enable_read_channels", "Читати канали"], ["enable_account_dialogs", "Діалоги між акаунтами"], ["enable_story_view", "Перегляд сторіс"], ["enable_join_groups", "Вступати в групи"], ["enable_trust_boost", "Підвищення довіри"]]],
  ["Читання", [["enable_view_dialogs", "Перегляд діалогів"], ["enable_channel_scroll", "Прокрутка каналів"], ["enable_mark_read", "Відмітити як прочитано"], ["enable_message_search", "Пошук повідомлень"]]],
  ["Соціальні", [["enable_forward_messages", "Пересилка повідомлень"], ["enable_saved_notes", "Нотатки в обраному"], ["enable_typing_simulation", "Симуляція набору"]]],
  ["Активність", [["enable_poll_scan", "Голосування"], ["enable_video_scan", "Перегляд відео"], ["enable_voice_scan", "Прослуховування voice"], ["enable_gif_search", "Пошук GIF"]]],
  ["Профіль і налаштування", [["enable_profile_view", "Перегляд профілів"], ["enable_settings_check", "Перевірка налаштувань"], ["enable_gradual_profile_check", "Поступове оновлення профілю"], ["enable_notification_check", "Сповіщення"]]],
  ["Розваги", [["enable_sticker_scan", "Стікери"], ["enable_inline_bot_check", "Inline-бот"], ["enable_link_preview", "Preview посилань"], ["enable_emoji_status_check", "Emoji-status"]]],
  ["Групи", [["enable_archive_check", "Архівування чатів"], ["enable_mute_check", "Вимкнення звуку"], ["enable_drafts_check", "Чернетки"], ["enable_scheduled_message_check", "Відкладені повідомлення"]]],
];

function Toggle({ checked, onChange, label }) {
  return (
    <label className="toggle-line">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="switch" />
      {label}
    </label>
  );
}

function levelForPolicy(policy) {
  if (policy.behavior_profile === "safe") return ["Обережний", "Для нових акаунтів 0-7 днів"];
  if (policy.behavior_profile === "aggressive") return ["Агресивний", "Для старих акаунтів 30+ днів"];
  return ["Нормальний", "Для прогрітих акаунтів 7-30 днів"];
}

export default function WarmupPage() {
  const [overview, setOverview] = useState({ policies: [], targets: [], plans: [], actions: [], logs: [] });
  const [accountsOverview, setAccountsOverview] = useState({ accounts: [] });
  const [parserOverview, setParserOverview] = useState({ channel_templates: [] });
  const [policy, setPolicy] = useState(defaultPolicy);
  const [selectedAccounts, setSelectedAccounts] = useState([]);
  const [targetText, setTargetText] = useState("");
  const [selectedTargets, setSelectedTargets] = useState([]);
  const [selectedChannelTemplateId, setSelectedChannelTemplateId] = useState(null);
  const [session, setSession] = useState("30");
  const [timezone, setTimezone] = useState("Europe/Kyiv");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const policyDirtyRef = useRef(false);

  async function load({ forcePolicySync = false } = {}) {
    setError("");
    try {
      await apiFetch("/api/v1/auth/me/");
      const [warmup, accounts, parser] = await Promise.all([
        apiFetch("/api/v1/warmup/overview/"),
        apiFetch("/api/v1/accounts/overview/"),
        apiFetch("/api/v1/parser/channels/overview/"),
      ]);
      setOverview(warmup);
      setAccountsOverview(accounts);
      setParserOverview(parser);
      setSelectedTargets((prev) => {
        const existingIds = new Set((warmup.targets || []).map((target) => target.id));
        return prev.filter((id) => existingIds.has(id));
      });
      if (warmup.policies?.[0] && (forcePolicySync || !policyDirtyRef.current)) {
        setPolicy({ ...defaultPolicy, ...warmup.policies[0] });
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
    const timer = setInterval(load, 12000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const connectedAccounts = useMemo(
    () => accountsOverview.accounts.filter((account) => account.is_attached && account.auth_state === "connected"),
    [accountsOverview.accounts],
  );

  const [levelName, levelDescription] = levelForPolicy(policy);
  const policiesById = useMemo(() => new Map((overview.policies || []).map((item) => [item.id, item])), [overview.policies]);
  const visibleLogs = useMemo(
    () =>
      (overview.logs || []).filter((log) => {
        const messageText = log.message || "";
        return !(
          messageText.includes("Заплановано") ||
          messageText.includes("Виконується") ||
          messageText.includes("План «")
        );
      }),
    [overview.logs],
  );

  function planProgress(plan) {
    const planPolicy = policiesById.get(plan.policy) || policy;
    const durationMs = Math.max(1, Number(planPolicy.session_duration_minutes || session || 30)) * 60 * 1000;
    const startedMs = plan.started_at ? new Date(plan.started_at).getTime() : now;
    const elapsedMs = Math.max(0, now - startedMs);
    const percent = Math.min(100, Math.floor((elapsedMs / durationMs) * 100));
    const remainingMs = Math.max(0, durationMs - elapsedMs);
    const remainingMinutes = Math.floor(remainingMs / 60000);
    const remainingSeconds = Math.floor((remainingMs % 60000) / 1000);
    return {
      percent,
      remaining: `${remainingMinutes}м ${String(remainingSeconds).padStart(2, "0")}с`,
    };
  }

  function updatePolicyField(field, value) {
    policyDirtyRef.current = true;
    setPolicy((prev) => ({ ...prev, [field]: value }));
  }

  async function savePolicy() {
    setError("");
    setMessage("");
    const body = { ...policy, session_duration_minutes: Number(session) || policy.session_duration_minutes };
    try {
      const saved = policy.id
        ? await apiFetch(`/api/v1/warmup/policies/${policy.id}/`, { method: "PUT", body })
        : await apiFetch("/api/v1/warmup/policies/add/", { method: "POST", body });
      policyDirtyRef.current = false;
      setPolicy({ ...defaultPolicy, ...saved });
      setMessage("Налаштування прогріву збережено.");
      load();
      return saved;
    } catch (exc) {
      setError(normalizeApiError(exc));
      return null;
    }
  }

  async function importTargets() {
    setError("");
    if (!targetText.trim()) return overview.targets;
    try {
      await apiFetch("/api/v1/warmup/targets/bulk-import/", {
        method: "POST",
        body: { targets: targetText, visibility: "public" },
      });
      setTargetText("");
      await load();
      const refreshed = await apiFetch("/api/v1/warmup/overview/");
      setOverview(refreshed);
      return refreshed.targets;
    } catch (exc) {
      setError(normalizeApiError(exc));
      return [];
    }
  }

  async function importChannelTemplate(templateId) {
    setError("");
    try {
      const response = await apiFetch("/api/v1/warmup/targets/import-channel-template/", {
        method: "POST",
        body: { template_id: templateId, visibility: "public" },
      });
      return response;
    } catch (exc) {
      setError(normalizeApiError(exc));
      return null;
    }
  }

  async function startWarmup() {
    setError("");
    setMessage("");
    const savedPolicy = await savePolicy();
    if (!savedPolicy) return;
    const targets = await importTargets();
    let templateTargetIds = [];
    if (selectedChannelTemplateId) {
      const importedTemplate = await importChannelTemplate(selectedChannelTemplateId);
      if (!importedTemplate) return;
      templateTargetIds = importedTemplate.target_ids || [];
    }
    const availableTargetIds = new Set((targets || []).map((target) => target.id));
    const normalizedSelectedTargets = selectedTargets.filter((id) => availableTargetIds.has(id));
    if (normalizedSelectedTargets.length !== selectedTargets.length) {
      setSelectedTargets(normalizedSelectedTargets);
    }
    const ids = Array.from(new Set([
      ...templateTargetIds,
      ...(normalizedSelectedTargets.length ? normalizedSelectedTargets : (targets || []).map((target) => target.id)),
    ]));
    if (!selectedAccounts.length) {
      setError("Виберіть акаунти для прогріву.");
      return;
    }
    if (!ids.length) {
      setError("Додайте або виберіть групи/канали для вступу.");
      return;
    }
    try {
      const plan = await apiFetch("/api/v1/warmup/plans/add/", {
        method: "POST",
        body: {
          name: `Warmup ${new Date().toLocaleString("uk-UA")}`,
          policy: savedPolicy.id,
          account_ids: selectedAccounts,
          target_ids: ids,
        },
      });
      await apiFetch(`/api/v1/warmup/plans/${plan.id}/start/`, { method: "POST", body: {} });
      setMessage("Прогрів запущено. Дії виконуються по колу, доки ви не натиснете Stop.");
      load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    }
  }

  async function stopPlan(planId) {
    await apiFetch(`/api/v1/warmup/plans/${planId}/stop/`, { method: "POST", body: { purge_redis: true } });
    load();
  }

  async function clearAll() {
    await apiFetch("/api/v1/warmup/actions/clear/", {
      method: "POST",
      body: { mode: "all", clear_logs: true, purge_redis: true },
    });
    load();
  }

  async function deleteTarget(targetId) {
    setSelectedTargets((prev) => prev.filter((id) => id !== targetId));
    await apiFetch(`/api/v1/warmup/targets/${targetId}/`, { method: "DELETE" });
    load();
  }

  return (
    <AppShell>
      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert success">{message}</div>}

      <section className="warmup-card hero-card">
        <div>
          <div className="eyebrow">setup</div>
          <h2>Прогрів: налаштування</h2>
          <p>Модуль імітує природну активність Telegram акаунтів: вступи, читання, реакції, перегляди і технічні перевірки.</p>
        </div>
        <button className="ghost-button" onClick={load}>Оновити</button>
      </section>

      <section className="warmup-card">
        <div className="section-title">
          <span className="section-icon green">⚙</span>
          <div><h3>Налаштування прогріву</h3><p>Розклад активності та автопідбір лімітів</p></div>
          <button className="ghost-button" onClick={savePolicy}>Зберегти</button>
        </div>
        <div className="warmup-grid two">
          <div className="dashed-panel">
            <h4>Розклад активності</h4>
            <div className="field-row">
              <label>Активність з<input type="number" min="0" max="23" value={policy.active_start_hour} onChange={(e) => updatePolicyField("active_start_hour", Number(e.target.value))} /></label>
              <label>до<input type="number" min="0" max="23" value={policy.active_end_hour} onChange={(e) => updatePolicyField("active_end_hour", Number(e.target.value))} /></label>
            </div>
            <label>Таймзона
              <select value={timezone} onChange={(e) => setTimezone(e.target.value)}>
                <option value="Europe/Kyiv">UTC+2 Kyiv</option>
                <option value="Europe/Warsaw">UTC+1 Warsaw</option>
                <option value="Europe/Berlin">UTC+1 Berlin</option>
                <option value="Europe/London">UTC+0 London</option>
                <option value="America/New_York">UTC-5 New York</option>
              </select>
            </label>
            <Toggle checked={policy.random_breaks} onChange={(value) => updatePolicyField("random_breaks", value)} label="Випадкові перерви" />
          </div>
          <div className="dashed-panel">
            <h4>Інтенсивність прогріву</h4>
            <div className="intensity-list">
              {[
                ["safe", "🐢 Обережний", "Для нових акаунтів"],
                ["balanced", "⚖ Нормальний", "Для прогрітих акаунтів"],
                ["aggressive", "🚀 Агресивний", "Для старих акаунтів"],
              ].map(([value, title, desc]) => (
                <button key={value} className={policy.behavior_profile === value ? "active" : ""} onClick={() => updatePolicyField("behavior_profile", value)}>
                  <b>{title}</b><span>{desc}</span>
                </button>
              ))}
            </div>
            <Toggle checked={policy.auto_adapt_limits} onChange={(value) => updatePolicyField("auto_adapt_limits", value)} label="Автоадаптація по стадії акаунта" />
          </div>
        </div>
      </section>

      <section className="warmup-card danger-soft">
        <div className="section-title">
          <span className="section-icon red">◇</span>
          <div><h3>Ліміти безпеки</h3><p>Захист від блокувань Telegram</p></div>
        </div>
        <div className="field-row four">
          <label>Дій/час<input type="number" min="1" max="120" value={policy.actions_per_hour} onChange={(e) => updatePolicyField("actions_per_hour", Number(e.target.value))} /></label>
          <label>Дій/день<input type="number" min="1" max="500" value={policy.actions_per_day} onChange={(e) => updatePolicyField("actions_per_day", Number(e.target.value))} /></label>
          <label>Вступів/день<input type="number" min="1" max="50" value={policy.daily_join_max} onChange={(e) => updatePolicyField("daily_join_max", Number(e.target.value))} /></label>
          <label>Повідомлень/день<input type="number" min="0" max="500" value={policy.messages_per_day} onChange={(e) => updatePolicyField("messages_per_day", Number(e.target.value))} /></label>
        </div>
        <Toggle checked={policy.progressive_ramp} onChange={(value) => updatePolicyField("progressive_ramp", value)} label="Прогресивне збільшення активності" />
      </section>

      <section className="warmup-card">
        <div className="section-title">
          <span className="section-icon blue">↗</span>
          <div><h3>Підписки та вступи</h3><p>Folder addlist стартує одразу, список каналів і груп іде за інтервалами</p></div>
        </div>
        <div className="warmup-grid two">
          <div className="dashed-panel">
            <h4>Методи вступу</h4>
            <Toggle checked={policy.allow_folder_one_click} onChange={(value) => updatePolicyField("allow_folder_one_click", value)} label="Папка t.me/addlist одним кліком" />
            <Toggle checked={policy.allow_public_gradual_join} onChange={(value) => updatePolicyField("allow_public_gradual_join", value)} label="Публічні канали поступово" />
            <Toggle checked={policy.allow_private_join} onChange={(value) => updatePolicyField("allow_private_join", value)} label="Приватні invite targets" />
          </div>
          <div className="dashed-panel">
            <h4>Інтервали вступу</h4>
            <div className="field-row">
              <label>Join/day min<input type="number" min="1" max="50" value={policy.daily_join_min} onChange={(e) => updatePolicyField("daily_join_min", Number(e.target.value))} /></label>
              <label>Join/day max<input type="number" min="1" max="50" value={policy.daily_join_max} onChange={(e) => updatePolicyField("daily_join_max", Number(e.target.value))} /></label>
              <label>Delay min sec<input type="number" min="60" value={policy.delay_min_seconds} onChange={(e) => updatePolicyField("delay_min_seconds", Number(e.target.value))} /></label>
              <label>Delay max sec<input type="number" min="60" value={policy.delay_max_seconds} onChange={(e) => updatePolicyField("delay_max_seconds", Number(e.target.value))} /></label>
            </div>
          </div>
        </div>
      </section>

      <section className="warmup-card">
        <div className="section-title">
          <span className="section-icon violet">◷</span>
          <div><h3>Тривалість сесії</h3><p>Бот гріється по колу до натискання Stop</p></div>
        </div>
        <div className="session-options">
          {[["30", "30 хв"], ["60", "1 час"], ["120", "2 часи"], ["480", "8 год"], ["1440", "1 день"], ["4320", "3 дні"], ["10080", "7 днів"]].map(([value, label]) => (
            <button key={value} className={session === value ? "active" : ""} onClick={() => setSession(value)}>{label}</button>
          ))}
        </div>
      </section>

      <section className="warmup-card success-soft">
        <div className="section-title">
          <span className="section-icon green">✓</span>
          <div><h3>Дії прогріву</h3><p>Усі дії виконуються у випадковому порядку</p></div>
        </div>
        <div className="dashed-panel old-actions-panel">
          <h4>Сценарій зі старого прогрівача</h4>
          <div className="old-actions-grid">
            {actionGroups[0][1].map(([field, label]) => (
              <Toggle key={field} checked={Boolean(policy[field])} onChange={(value) => updatePolicyField(field, value)} label={label} />
            ))}
          </div>
          <div className="field-row compact">
            <label>Джерело прогріву
              <select
                value={policy.enable_read_channels ? policy.warmup_source : "disabled"}
                onChange={(e) => {
                  const value = e.target.value;
                  updatePolicyField("enable_read_channels", value !== "disabled");
                  if (value !== "disabled") updatePolicyField("warmup_source", value);
                }}
              >
                <option value="subscriptions">Із підписок</option>
                <option value="targets">Із targets</option>
                <option value="disabled">Вимкнено</option>
              </select>
            </label>
            <label>Вступ у групи
              <select value={policy.enable_join_groups ? "random" : "disabled"} onChange={(e) => updatePolicyField("enable_join_groups", e.target.value !== "disabled")}>
                <option value="random">Рандомні</option>
                <option value="targets">Тільки targets</option>
                <option value="disabled">Вимкнено</option>
              </select>
            </label>
          </div>
        </div>
        <div className="action-groups">
          {actionGroups.slice(1).map(([title, items]) => (
            <div className="action-group" key={title}>
              <h4>{title}</h4>
              {items.map(([field, label]) => (
                <Toggle key={field} checked={Boolean(policy[field])} onChange={(value) => updatePolicyField(field, value)} label={label} />
              ))}
            </div>
          ))}
        </div>
        <div className="field-row">
          <label>Search query<input value={policy.search_query} onChange={(e) => updatePolicyField("search_query", e.target.value)} /></label>
          <label>Inline bot username<input value={policy.inline_bot_username} onChange={(e) => updatePolicyField("inline_bot_username", e.target.value)} /></label>
        </div>
      </section>

      <section className="warmup-card">
        <div className="section-title">
          <span className="section-icon blue">♙</span>
          <div><h3>Які акаунти прогріти</h3><p>Виберіть валідні акаунти з менеджера</p></div>
        </div>
        <div className="account-picker">
          {connectedAccounts.map((account) => (
            <button key={account.id} className={selectedAccounts.includes(account.id) ? "active" : ""} onClick={() => setSelectedAccounts((prev) => prev.includes(account.id) ? prev.filter((id) => id !== account.id) : [...prev, account.id])}>
              <b>{account.label}</b><span>{account.phone_number || account.telegram_username || `#${account.id}`}</span>
            </button>
          ))}
          {!connectedAccounts.length && <div className="empty-state">Немає підключених акаунтів.</div>}
        </div>
      </section>

      <section className="warmup-card pink-soft">
        <div className="section-title">
          <span className="section-icon pink">⌖</span>
          <div><h3>Для вступлення</h3><p>Додайте folder addlist або список @username / t.me каналів і груп</p></div>
        </div>
        {!!(parserOverview.channel_templates || []).length && (
          <div className="target-list" style={{ marginBottom: 14 }}>
            {parserOverview.channel_templates.map((template) => (
              <button
                key={template.id}
                type="button"
                className={selectedChannelTemplateId === template.id ? "active" : ""}
                onClick={() => setSelectedChannelTemplateId((prev) => (prev === template.id ? null : template.id))}
              >
                <b>{template.name}</b>
                <span>{template.item_count || 0} каналів із шаблону</span>
              </button>
            ))}
          </div>
        )}
        <textarea className="large-textarea" value={targetText} onChange={(e) => setTargetText(e.target.value)} placeholder={"https://t.me/addlist/...\n@cryptogroup\nhttps://t.me/joinchat/..."} />
      </section>

      <section className="warmup-card launch-panel">
        <div className="launch-stats">
          <div><span>Акаунти</span><b>{selectedAccounts.length}</b></div>
          <div><span>Тривалість</span><b>{session} хв</b></div>
          <div><span>Інтенсивність</span><b>{levelName}</b><small>{levelDescription}</small></div>
          <div><span>Ліміти</span><b>{policy.actions_per_day}/день</b></div>
        </div>
        <div className="launch-box">
          <button className="primary-button big" onClick={startWarmup}>▷ Запустити прогрів</button>
          <span className="state-dot">● Очікує запуску</span>
          <button className="ghost-button" onClick={clearAll}>Очистити історію</button>
        </div>
      </section>

      <section className="warmup-card">
        <div className="section-title">
          <span className="section-icon blue">☰</span>
          <div><h3>Плани прогріву</h3><p>Керування активними циклами</p></div>
        </div>
        <div className="plan-grid">
          {overview.plans.map((plan) => {
            const progress = planProgress(plan);
            return (
              <article key={plan.id} className="plan-card">
                <div><b>{plan.name}</b><span>{plan.account_count} акаунт(ів), {plan.target_count} target(ів)</span></div>
                <strong className={`badge ${plan.status === "running" ? "green" : "gray"}`}>{plan.status}</strong>
                <small>queue {plan.queued_count} · ok {plan.succeeded_count} · failed {plan.failed_count}</small>
                <div className="session-progress">
                  <div>
                    <span>{progress.percent}%</span>
                    <b>{progress.remaining}</b>
                  </div>
                  <i><em style={{ width: `${progress.percent}%` }} /></i>
                </div>
                <button onClick={() => stopPlan(plan.id)}>Stop</button>
              </article>
            );
          })}
        </div>
      </section>

      <section className="warmup-card logs-card">
        <div className="log-toolbar">
          <span className="online-dot">● в мережі</span>
          <span>Усі {visibleLogs.length}</span>
          <span>Успіх {visibleLogs.filter((log) => log.level === "success" || log.level === "info").length}</span>
          <span>Помилки {visibleLogs.filter((log) => log.level === "error").length}</span>
        </div>
        <div className="terminal">
          {visibleLogs.length === 0 && <div className="empty-state">Логів поки немає</div>}
          {[...visibleLogs].reverse().map((log) => (
            <div key={log.id} className={`terminal-line ${log.level}`}>
              <time>{new Date(log.created_at).toLocaleTimeString("uk-UA")}</time>
              <span>{log.level === "error" ? "❌" : log.level === "warning" ? "⚠️" : "✅"}</span>
              <b>{log.account_label || "system"}</b>
              <p>{log.message}</p>
            </div>
          ))}
        </div>
      </section>
    </AppShell>
  );
}
