"use client";

import { useEffect, useMemo, useState } from "react";
import AppShell from "@/components/AppShell";
import { apiFetch, authTokens, backendApiUrl, mediaUrl, normalizeApiError } from "@/lib/api";

const emptyOverview = {
  account_count: 0,
  attached_count: 0,
  connected_count: 0,
  quarantined_count: 0,
  pending_auth_count: 0,
  proxy_count: 0,
  accounts: [],
  proxies: [],
};

const statusLabels = {
  connected: "Valid",
  pending_code: "SMS",
  pending_2fa: "2FA",
  failed: "Reauthorization",
  detached: "Detached",
  session_uploaded: "Uploaded",
};

function initials(account) {
  const base = `${account.first_name || ""} ${account.last_name || ""}`.trim() || account.label || "?";
  return base.slice(0, 2).toUpperCase();
}

function accountName(account) {
  return `${account.first_name || ""} ${account.last_name || ""}`.trim() || account.label;
}

function AccountAvatar({ account, size = "" }) {
  const src = mediaUrl(account.avatar_url);
  return (
    <span className={`avatar ${size}`}>
      {src ? <img src={src} alt={accountName(account)} /> : initials(account)}
    </span>
  );
}

function proxyLabel(proxies, id) {
  const proxy = proxies.find((item) => item.id === id);
  if (!proxy) return "Без проксі";
  const latency = proxy.last_latency_ms ? `${proxy.last_latency_ms}ms` : "не перевірено";
  return `${proxy.name} · ${latency}`;
}

function compactDate(value) {
  if (!value) return "";
  try {
    return new Intl.DateTimeFormat("uk-UA", {
      hour: "2-digit",
      minute: "2-digit",
      day: "2-digit",
      month: "2-digit",
    }).format(new Date(value));
  } catch {
    return "";
  }
}

function accountRiskLabel(value) {
  if (value === "high") return "Високий ризик";
  if (value === "medium") return "Середній ризик";
  return "Низький ризик";
}

function accountRiskTone(value) {
  if (value === "high") return "red";
  if (value === "medium") return "amber";
  return "green";
}

function quarantineLabel(account) {
  if (!account.is_quarantined || !account.quarantine_until) return "";
  return `Карантин до ${compactDate(account.quarantine_until)}`;
}

function operationalRoleLabel(account) {
  if (account.operational_role_label) return account.operational_role_label;
  if (account.operational_role === "warmup") return "Прогрів";
  if (account.operational_role === "parsing") return "Парсинг";
  return "Резерв";
}

function operationalRoleTone(account) {
  if (account.operational_role === "warmup") return "amber";
  if (account.operational_role === "parsing") return "blue";
  return "green";
}

function warmupAgeLabel(account) {
  const days = Number.isFinite(Number(account.warmup_age_days)) ? Number(account.warmup_age_days) : 0;
  return `Прогрів ${days}д`;
}

function accountStatusLabel(account) {
  if (account.is_quarantined) return quarantineLabel(account);
  if (account.operational_role === "warmup") {
    return account.current_warmup_action_label || "Прогрів";
  }
  return statusLabels[account.auth_state] || account.auth_state;
}

function accountStatusTone(account) {
  if (account.is_quarantined) return "amber";
  if (account.operational_role === "warmup") {
    return account.current_warmup_action_status === "running" ? "blue" : "amber";
  }
  if (account.auth_state === "connected") return "green";
  if (account.auth_state === "failed") return "red";
  return "amber";
}

function StatCard({ icon, label, value, tone }) {
  return (
    <div className={`stat-card ${tone || ""}`}>
      <div className="stat-icon">{icon}</div>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function Modal({ title, children, onClose, wide }) {
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className={`modal ${wide ? "wide" : ""}`} onMouseDown={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        <h2>{title}</h2>
        {children}
      </section>
    </div>
  );
}

function AddAccountModal({ proxies, onClose, onSaved }) {
  const [step, setStep] = useState(1);
  const [account, setAccount] = useState(null);
  const [form, setForm] = useState({
    label: "",
    phone_number: "",
    proxy: "",
    proxy_line: "",
    requires_2fa: false,
  });
  const [code, setCode] = useState("");
  const [password2fa, setPassword2fa] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submitPhone(event) {
    event.preventDefault();
    setError("");
    const phone = form.phone_number.replace(/[^\d+]/g, "");
    if (!/^\+?[1-9]\d{7,14}$/.test(phone)) {
      setError("Вкажіть номер у міжнародному форматі.");
      return;
    }
    setBusy(true);
    try {
      const body = new FormData();
      body.append("attach_mode", "credentials");
      body.append("label", form.label || phone);
      body.append("phone_number", phone);
      body.append("requires_2fa", form.requires_2fa ? "true" : "false");
      if (form.proxy) body.append("proxy", form.proxy);
      const created = await apiFetch("/api/v1/accounts/add/", { method: "POST", body });
      setAccount(created);
      setStep(created.auth_state === "pending_2fa" ? 3 : 2);
      onSaved();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy(false);
    }
  }

  async function completeAuth(event) {
    event.preventDefault();
    if (!account) return;
    setError("");
    setBusy(true);
    try {
      const updated = await apiFetch(`/api/v1/accounts/${account.id}/complete-auth/`, {
        method: "POST",
        body: { verification_code: code, password_2fa: password2fa },
      });
      setAccount(updated);
      if (updated.auth_state === "pending_2fa") {
        setStep(3);
      } else if (updated.auth_state === "connected") {
        setStep(4);
        onSaved();
      } else {
        setError(updated.last_auth_error || "Telegram не підтвердив авторизацію.");
      }
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Додати акаунт" onClose={onClose} wide>
      <div className="stepper">
        {["Номер телефону", "SMS код", "2FA", "Успіх"].map((label, index) => (
          <span key={label} className={step >= index + 1 ? "active" : ""}>
            <b>{index + 1}</b>{label}
          </span>
        ))}
      </div>

      {error && <div className="alert error">{error}</div>}

      {step === 1 && (
        <form className="modal-grid" onSubmit={submitPhone}>
          <label>
            Назва акаунта
            <input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} placeholder="Main Seller UA" />
          </label>
          <label>
            Номер телефону
            <input value={form.phone_number} onChange={(e) => setForm({ ...form, phone_number: e.target.value })} placeholder="+380123456789" />
            <small>Префікс `+` можна не вводити, сервер нормалізує формат.</small>
          </label>
          <label>
            Проксі для акаунта
            <select value={form.proxy} onChange={(e) => setForm({ ...form, proxy: e.target.value })}>
              <option value="">Без проксі</option>
              {proxies.map((proxy) => <option key={proxy.id} value={proxy.id}>{proxy.name} · {proxy.host}:{proxy.port}</option>)}
            </select>
          </label>
          <label className="checkbox-line">
            <input type="checkbox" checked={form.requires_2fa} onChange={(e) => setForm({ ...form, requires_2fa: e.target.checked })} />
            Акаунт може мати 2FA пароль
          </label>
          <button className="primary-button modal-submit" disabled={busy}>{busy ? "Надсилаю..." : "Надіслати SMS код"}</button>
        </form>
      )}

      {step === 2 && (
        <form className="modal-grid" onSubmit={completeAuth}>
          <label>
            SMS / Telegram код
            <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} placeholder="12345" />
          </label>
          <button className="primary-button modal-submit" disabled={busy}>{busy ? "Перевіряю..." : "Підтвердити код"}</button>
        </form>
      )}

      {step === 3 && (
        <form className="modal-grid" onSubmit={completeAuth}>
          <label>
            2FA пароль
            <input type="password" value={password2fa} onChange={(e) => setPassword2fa(e.target.value)} placeholder="Пароль двоетапної перевірки" />
          </label>
          <button className="primary-button modal-submit" disabled={busy}>{busy ? "Авторизую..." : "Завершити авторизацію"}</button>
        </form>
      )}

      {step === 4 && (
        <div className="success-panel">
          <strong>Акаунт підключено до StogramGPT.</strong>
          <button className="primary-button" onClick={onClose}>Закрити</button>
        </div>
      )}
    </Modal>
  );
}

function ReauthAccountModal({ initialAccount, onClose, onSaved }) {
  const [step, setStep] = useState(initialAccount?.auth_state === "pending_2fa" ? 3 : 2);
  const [account, setAccount] = useState(initialAccount);
  const [code, setCode] = useState("");
  const [password2fa, setPassword2fa] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function resend() {
    if (!account) return;
    setError("");
    setBusy(true);
    try {
      const updated = await apiFetch(`/api/v1/accounts/${account.id}/resend-code/`, { method: "POST", body: {} });
      setAccount(updated);
      setCode("");
      setPassword2fa("");
      setStep(updated.auth_state === "pending_2fa" ? 3 : 2);
      await onSaved();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy(false);
    }
  }

  async function completeAuth(event) {
    event.preventDefault();
    if (!account) return;
    setError("");
    setBusy(true);
    try {
      const updated = await apiFetch(`/api/v1/accounts/${account.id}/complete-auth/`, {
        method: "POST",
        body: { verification_code: code, password_2fa: password2fa },
      });
      setAccount(updated);
      if (updated.auth_state === "pending_2fa") {
        setStep(3);
      } else if (updated.auth_state === "connected") {
        setStep(4);
        await onSaved();
      } else {
        setError(updated.last_auth_error || "Telegram не підтвердив авторизацію.");
      }
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Переавторизація акаунта" onClose={onClose} wide>
      <div className="stepper">
        {["SMS код", "2FA", "Готово"].map((label, index) => (
          <span key={label} className={step >= index + 2 ? "active" : ""}>
            <b>{index + 2}</b>{label}
          </span>
        ))}
      </div>

      <div className="alert">
        {accountName(account || {})} · {account?.phone_number || "номер не задано"}
      </div>
      {error && <div className="alert error">{error}</div>}

      {step === 2 && (
        <form className="modal-grid" onSubmit={completeAuth}>
          <label>
            SMS / Telegram код
            <input value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))} placeholder="12345" />
            <small>Код приходить у Telegram/SMS. Якщо після коду потрібен пароль, форма автоматично перейде на 2FA.</small>
          </label>
          <div className="inline-actions">
            <button type="submit" className="primary-button" disabled={busy}>{busy ? "Перевіряю..." : "Підтвердити код"}</button>
            <button type="button" onClick={resend} disabled={busy}>{busy ? "Надсилаю..." : "Надіслати код знову"}</button>
          </div>
        </form>
      )}

      {step === 3 && (
        <form className="modal-grid" onSubmit={completeAuth}>
          <label>
            2FA пароль
            <input type="password" value={password2fa} onChange={(event) => setPassword2fa(event.target.value)} placeholder="Пароль двоетапної перевірки" />
            <small>Це cloud password Telegram. Код повторно вводити не потрібно.</small>
          </label>
          <div className="inline-actions">
            <button type="submit" className="primary-button" disabled={busy}>{busy ? "Авторизую..." : "Завершити авторизацію"}</button>
            <button type="button" onClick={() => setStep(2)} disabled={busy}>Назад до коду</button>
          </div>
        </form>
      )}

      {step === 4 && (
        <div className="success-panel">
          <strong>Акаунт переавторизовано.</strong>
          <button className="primary-button" onClick={onClose}>Закрити</button>
        </div>
      )}
    </Modal>
  );
}

function Set2FAModal({ accounts, onClose, onSaved }) {
  const [form, setForm] = useState({ current_password: "", new_password: "", hint: "", email: "" });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    if (form.new_password.length < 8) {
      setError("Новий 2FA пароль має містити мінімум 8 символів.");
      return;
    }
    setBusy(true);
    try {
      for (const account of accounts) {
        await apiFetch(`/api/v1/accounts/telegram-accounts/${account.id}/set-2fa/`, {
          method: "POST",
          body: form,
        });
      }
      setNotice(`2FA оновлено для ${accounts.length} акаунт(ів).`);
      await onSaved();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Установити 2FA" onClose={onClose} wide>
      <form className="modal-grid" onSubmit={submit}>
        <div className="alert">Вибрано: {accounts.map(accountName).join(", ")}</div>
        {error && <div className="alert error">{error}</div>}
        {notice && <div className="alert success">{notice}</div>}
        <label>
          Поточний 2FA пароль
          <input type="password" value={form.current_password} onChange={(e) => setForm({ ...form, current_password: e.target.value })} placeholder="Заповніть, якщо пароль вже існує" />
        </label>
        <label>
          Новий 2FA пароль
          <input type="password" value={form.new_password} onChange={(e) => setForm({ ...form, new_password: e.target.value })} placeholder="Мінімум 8 символів" />
        </label>
        <label>
          Hint
          <input value={form.hint} onChange={(e) => setForm({ ...form, hint: e.target.value })} placeholder="Підказка для пароля" />
        </label>
        <label>
          Email recovery
          <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="optional@email.com" />
        </label>
        <button className="primary-button modal-submit" disabled={busy}>{busy ? "Оновлюю..." : "Зберегти 2FA"}</button>
      </form>
    </Modal>
  );
}

function CreateChannelModal({ accounts, onClose, onSaved }) {
  const [form, setForm] = useState({ title: "", description: "", supergroup: false });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    if (form.title.trim().length < 3) {
      setError("Назва каналу має містити мінімум 3 символи.");
      return;
    }
    setBusy(true);
    try {
      const created = [];
      for (const account of accounts) {
        const result = await apiFetch(`/api/v1/accounts/telegram-accounts/${account.id}/create-channel/`, {
          method: "POST",
          body: form,
        });
        created.push(result.title || form.title);
      }
      setNotice(`Створено: ${created.join(", ")}`);
      await onSaved();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Створити канал" onClose={onClose} wide>
      <form className="modal-grid" onSubmit={submit}>
        <div className="alert">Канал буде створено від: {accounts.map(accountName).join(", ")}</div>
        {error && <div className="alert error">{error}</div>}
        {notice && <div className="alert success">{notice}</div>}
        <label>
          Назва каналу
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Crypto Drops UA" />
        </label>
        <label>
          Опис
          <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Короткий опис каналу" />
        </label>
        <label className="checkbox-line">
          <input type="checkbox" checked={form.supergroup} onChange={(e) => setForm({ ...form, supergroup: e.target.checked })} />
          Створити групу замість каналу
        </label>
        <button className="primary-button modal-submit" disabled={busy}>{busy ? "Створюю..." : "Створити"}</button>
      </form>
    </Modal>
  );
}

function ImportAccountsModal({ proxies, onClose, onSaved }) {
  const [files, setFiles] = useState([]);
  const [proxy, setProxy] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const sessionFiles = files.filter((file) => file.name.endsWith(".session"));
  const tdataFiles = files.filter((file) => !file.name.endsWith(".session"));

  async function importSessions() {
    setError("");
    if (!sessionFiles.length) {
      setError("Зараз backend приймає Pyrogram `.session`. TData додано в UI, але його конвертацію потрібно окремо реалізувати на сервері.");
      return;
    }
    setBusy(true);
    try {
      for (const file of sessionFiles) {
        const body = new FormData();
        body.append("attach_mode", "session");
        body.append("label", file.name.replace(/\.session$/i, ""));
        body.append("session_file", file);
        if (proxy) body.append("proxy", proxy);
        await apiFetch("/api/v1/accounts/add/", { method: "POST", body });
      }
      onSaved();
      onClose();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Імпортувати акаунти" onClose={onClose} wide>
      <div className="import-grid">
        <label className="drop-zone tdata">
          <input type="file" webkitdirectory="true" directory="" multiple onChange={(e) => setFiles(Array.from(e.target.files || []))} />
          <span>▣</span>
          <strong>TData</strong>
          <small>Папка приймається в UI; серверна конвертація ще не підключена.</small>
        </label>
        <label className="drop-zone session">
          <input type="file" accept=".session" multiple onChange={(e) => setFiles(Array.from(e.target.files || []))} />
          <span>◰</span>
          <strong>.session</strong>
          <small>Готовий Pyrogram session файл.</small>
        </label>
      </div>

      <div className="modal-grid two">
        <label>
          Вибрати проксі
          <select value={proxy} onChange={(e) => setProxy(e.target.value)}>
            <option value="">Без проксі</option>
            {proxies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label>
          Пул проксі
          <select disabled>
            <option>Опціонально, через Proxy Pool</option>
          </select>
        </label>
      </div>

      {error && <div className="alert error">{error}</div>}

      <div className="preview-table">
        <div className="preview-row head"><span>Акаунт</span><span>Формат</span><span>Проксі</span><span>Статус</span></div>
        {files.length === 0 && <div className="empty-state">Перетягніть або виберіть файли.</div>}
        {sessionFiles.map((file) => (
          <div className="preview-row" key={file.name}>
            <span>{file.name}</span><span>.session</span><span>{proxy || "не задано"}</span><span>готовий</span>
          </div>
        ))}
        {tdataFiles.length > 0 && <div className="preview-row muted"><span>TData файлів</span><span>{tdataFiles.length}</span><span>—</span><span>потрібна server-конвертація</span></div>}
      </div>

      <div className="modal-actions">
        <button className="warning-button" disabled>Перевірити акаунти</button>
        <button className="primary-button" onClick={importSessions} disabled={busy}>{busy ? "Зберігаю..." : "Зберегти в комбайн"}</button>
      </div>
    </Modal>
  );
}

function ProxyPoolModal({ proxies, onClose, onSaved }) {
  const [proxyText, setProxyText] = useState("");
  const [mode, setMode] = useState("sequential");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function parseProxy(line) {
    const value = line.trim();
    if (!value) return null;
    const normalized = value.includes("://") ? value : `socks5://${value}`;
    const url = new URL(normalized);
    if (!url.hostname || !url.port) throw new Error(`Некоректний проксі: ${line}`);
    return {
      name: `${url.protocol.replace(":", "")}-${url.hostname}-${url.port}`,
      protocol: url.protocol.replace(":", ""),
      host: url.hostname,
      port: Number(url.port),
      username: decodeURIComponent(url.username || ""),
      password: decodeURIComponent(url.password || ""),
    };
  }

  async function saveProxies() {
    setError("");
    setBusy(true);
    try {
      const parsed = proxyText.split(/\n|,/).map(parseProxy).filter(Boolean);
      if (!parsed.length) throw new Error("Додайте хоча б один проксі.");
      for (const item of parsed) {
        await apiFetch("/api/v1/accounts/proxies/add/", { method: "POST", body: item });
      }
      onSaved();
      onClose();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Пул проксі" onClose={onClose} wide>
      <div className="proxy-stats">
        <span>Ваші проксі: <b>{proxies.length}</b></span>
        <span>Активні: <b>{proxies.filter((p) => p.is_active).length}</b></span>
        <span>Помилки: <b>{proxies.filter((p) => p.status === "failed").length}</b></span>
      </div>
      <div className="segmented">
        <button className={mode === "sequential" ? "active" : ""} onClick={() => setMode("sequential")}>Послідовно</button>
        <button className={mode === "random" ? "active" : ""} onClick={() => setMode("random")}>Випадково</button>
      </div>
      <textarea
        className="large-textarea"
        value={proxyText}
        onChange={(e) => setProxyText(e.target.value)}
        placeholder={"1.2.3.4:1080:user:pass\nsocks5://user:pass@proxy.example.com:1080\nhttp://9.9.9.9:8080"}
      />
      {error && <div className="alert error">{error}</div>}
      <div className="modal-actions">
        <button className="ghost-button" disabled>Призначити проксі</button>
        <button className="primary-button" onClick={saveProxies} disabled={busy}>{busy ? "Зберігаю..." : "Перевірити і зберегти"}</button>
      </div>
    </Modal>
  );
}

function RoleTemplatesModal({ templates, onClose, onSaved }) {
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", prompt: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  function startEdit(template) {
    setEditing(template);
    setForm({ name: template.name, prompt: template.prompt });
    setError("");
  }

  async function saveTemplate(event) {
    event.preventDefault();
    setError("");
    setBusy("save-role");
    try {
      const path = editing ? `/api/v1/accounts/role-templates/${editing.id}/` : "/api/v1/accounts/role-templates/";
      await apiFetch(path, { method: editing ? "PATCH" : "POST", body: form });
      setEditing(null);
      setForm({ name: "", prompt: "" });
      await onSaved();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy("");
    }
  }

  async function deleteTemplate(template) {
    if (!window.confirm(`Видалити роль "${template.name}"?`)) return;
    setError("");
    setBusy(`delete-role-${template.id}`);
    try {
      await apiFetch(`/api/v1/accounts/role-templates/${template.id}/`, { method: "DELETE" });
      await onSaved();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy("");
    }
  }

  return (
    <Modal title="AI ролі акаунтів" onClose={onClose} wide>
      <div className="split-panel">
        <form className="modal-grid" onSubmit={saveTemplate}>
          <h3>{editing ? "Редагувати шаблон" : "Новий шаблон ролі"}</h3>
          <label>
            Назва
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Крипто інвесторка" />
          </label>
          <label>
            Prompt для ШІ
            <textarea
              className="large-textarea"
              value={form.prompt}
              onChange={(e) => setForm({ ...form, prompt: e.target.value })}
              placeholder="Ти досвідчена крипто інвесторка. Пиши коротко, впевнено, з фокусом на ризики, DYOR і практичні сигнали..."
            />
          </label>
          {error && <div className="alert error">{error}</div>}
          <div className="inline-actions">
            <button className="primary-button" disabled={busy === "save-role"}>{busy === "save-role" ? "Зберігаю..." : "Зберегти роль"}</button>
            {editing && <button type="button" onClick={() => { setEditing(null); setForm({ name: "", prompt: "" }); }}>Скасувати</button>}
          </div>
        </form>
        <div className="role-template-list">
          <h3>Збережені ролі</h3>
          {templates.map((template) => (
            <div key={template.id} className="role-template-card">
              <b>{template.name}</b>
              <p>{template.prompt}</p>
              <div className="inline-actions">
                <button onClick={() => startEdit(template)}>Редагувати</button>
                <button className="danger-text" onClick={() => deleteTemplate(template)} disabled={busy === `delete-role-${template.id}`}>Видалити</button>
              </div>
            </div>
          ))}
          {!templates.length && <div className="empty-state">Рольових шаблонів ще немає.</div>}
        </div>
      </div>
    </Modal>
  );
}

function AccountDetailsModal({ account, proxies, initialTab = "profile", onClose, onSaved }) {
  const [tab, setTab] = useState(initialTab);
  const [proxy, setProxy] = useState(account.proxy || "");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [health, setHealth] = useState(null);
  const [profile, setProfile] = useState({
    gender: "female",
    birth_date: account.birth_date || "",
    country: "Ukraine",
    profession: "crypto",
    telegram_channel: "@channel",
    bio: "",
  });
  const [draft, setDraft] = useState(null);

  async function assignProxy() {
    setError("");
    setNotice("");
    setBusy("proxy");
    try {
      await apiFetch(`/api/v1/accounts/${account.id}/proxy/`, { method: "POST", body: { proxy: proxy || null } });
      setNotice("Проксі оновлено.");
      await onSaved();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy("");
    }
  }

  async function createDraft() {
    setError("");
    setNotice("");
    setBusy("draft");
    try {
      const created = await apiFetch("/api/v1/profiles/drafts/", {
        method: "POST",
        body: { ...profile, account: account.id },
      });
      setDraft(created);
      setNotice("Чернетку профілю створено.");
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy("");
    }
  }

  async function draftAction(action) {
    if (!draft) return;
    setError("");
    setNotice("");
    setBusy(action);
    try {
      const updated = await apiFetch(`/api/v1/profiles/drafts/${draft.id}/${action}/`, { method: "POST", body: {} });
      setDraft(updated);
      setNotice(action === "apply" ? "Профіль застосовано." : "AI дія виконана.");
      if (action === "apply") await onSaved();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy("");
    }
  }

  async function saveAccountProfile() {
    setError("");
    setNotice("");
    setBusy("save-profile");
    try {
      await apiFetch(`/api/v1/accounts/telegram-accounts/${account.id}/`, {
        method: "PATCH",
        body: { birth_date: profile.birth_date || null },
      });
      setNotice("Дату народження збережено.");
      await onSaved();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy("");
    }
  }

  async function loadHealth() {
    setError("");
    setNotice("");
    setBusy("health");
    try {
      const payload = await apiFetch(`/api/v1/accounts/${account.id}/health/`);
      setHealth(payload);
      setNotice("Стан акаунта оновлено.");
      await onSaved();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy("");
    }
  }

  async function deleteAccount() {
    if (!window.confirm(`Повністю видалити акаунт "${accountName(account)}"?`)) return;
    setError("");
    setNotice("");
    setBusy("delete");
    try {
      await apiFetch(`/api/v1/accounts/telegram-accounts/${account.id}/`, { method: "DELETE" });
      await onSaved();
      onClose();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy("");
    }
  }

  async function recordAction(eventType, label) {
    setError("");
    setNotice("");
    setBusy(label);
    try {
      await apiFetch(`/api/v1/accounts/${account.id}/runtime-events/`, {
        method: "POST",
        body: { event_type: eventType, metadata: { source: "dashboard", action: label } },
      });
      setNotice(`Дію "${label}" відправлено.`);
      await onSaved();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy("");
    }
  }

  async function spamCheck() {
    setError("");
    setNotice("");
    setBusy("spam-check");
    try {
      const result = await apiFetch(`/api/v1/accounts/telegram-accounts/${account.id}/spam-check/`, { method: "POST", body: {} });
      setNotice(result.limited ? "SpamBot повідомив про обмеження." : "SpamBot не показав обмежень.");
      await onSaved();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy("");
    }
  }

  async function exportSession() {
    setError("");
    setNotice("");
    setBusy("export-session");
    try {
      const { access } = authTokens();
      const response = await fetch(backendApiUrl(`/api/v1/accounts/telegram-accounts/${account.id}/export-session/`), {
        headers: access ? { Authorization: `Bearer ${access}` } : {},
      });
      if (!response.ok) throw new Error(await response.text());
      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = `${account.session_name}.session`;
      link.click();
      URL.revokeObjectURL(href);
      setNotice("Session експортовано.");
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusy("");
    }
  }

  return (
    <Modal title="Управління акаунтом" onClose={onClose} wide>
      <div className="account-hero">
        <AccountAvatar account={account} size="xl" />
        <div>
          <h3>{accountName(account)}</h3>
          <p>@{account.telegram_username || "username"} · ID {account.telegram_user_id || account.id}</p>
          <p>{account.phone_number || "телефон не задано"}</p>
        </div>
        <div className="account-badges">
          <span className="badge green">{statusLabels[account.auth_state] || account.auth_state}</span>
          <span className="badge blue">Здоров'я {account.health_score}/100</span>
          <span className={`badge ${accountRiskTone(account.risk_level)}`}>Живучість {account.liveness_score ?? account.health_score}/100 · {accountRiskLabel(account.risk_level)}</span>
          <span className={`badge ${account.is_quarantined ? "amber" : "green"}`}>
            {account.is_quarantined ? quarantineLabel(account) : account.status}
          </span>
          {account.ggr_score != null && (
            <span className={`badge ${parseFloat(account.ggr_score) >= 7 ? "green" : parseFloat(account.ggr_score) >= 4 ? "amber" : "red"}`}>
              GGR {parseFloat(account.ggr_score).toFixed(1)}
            </span>
          )}
        </div>
      </div>

      <div className="tabs">
        {["profile", "proxy", "stats", "actions", "health"].map((item) => (
          <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item}</button>
        ))}
      </div>

      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert success">{notice}</div>}

      {tab === "profile" && (
        <div className="split-panel">
          <div className="modal-grid">
            <h3>AI редагування профілю</h3>
            <label>Стать
              <select value={profile.gender} onChange={(e) => setProfile({ ...profile, gender: e.target.value })}>
                <option value="female">Жінка</option>
                <option value="male">Чоловік</option>
                <option value="other">Інше</option>
              </select>
            </label>
            <label>Дата народження
              <input type="date" value={profile.birth_date} onChange={(e) => setProfile({ ...profile, birth_date: e.target.value })} />
            </label>
            <label>Країна
              <input value={profile.country} onChange={(e) => setProfile({ ...profile, country: e.target.value })} />
            </label>
            <label>Професія / ніша
              <input value={profile.profession} onChange={(e) => setProfile({ ...profile, profession: e.target.value })} />
            </label>
            <label>Канал для біо
              <input value={profile.telegram_channel} onChange={(e) => setProfile({ ...profile, telegram_channel: e.target.value })} />
            </label>
            <label>Біо вручну
              <textarea value={profile.bio} onChange={(e) => setProfile({ ...profile, bio: e.target.value.slice(0, 70) })} />
            </label>
            <div className="inline-actions">
              <button className="ghost-button" onClick={saveAccountProfile} disabled={busy === "save-profile"}>
                {busy === "save-profile" ? "Зберігаю..." : "Зберегти дату"}
              </button>
              <button className="primary-button" onClick={createDraft} disabled={busy === "draft"}>
                {busy === "draft" ? "Створюю..." : "Створити чернетку"}
              </button>
            </div>
            {draft && (
              <div className="inline-actions">
                <button onClick={() => draftAction("generate-bio")} disabled={busy === "generate-bio"}>AI біо</button>
                <button onClick={() => draftAction("generate-photo")} disabled={busy === "generate-photo"}>AI фото</button>
                <button onClick={() => draftAction("apply")} disabled={busy === "apply"}>Застосувати</button>
              </div>
            )}
          </div>
          <div className="telegram-preview">
            <AccountAvatar account={account} size="preview-avatar" />
            <h3>{accountName(account)}</h3>
            <p>last seen recently</p>
            <div className="preview-card">{draft?.bio || profile.bio || "Біо ще не задано"}</div>
            <div className="preview-card">@{account.telegram_username || "username"}</div>
            <div className="preview-card">{account.phone_number || "phone hidden"}</div>
          </div>
        </div>
      )}

      {tab === "proxy" && (
        <div className="modal-grid">
          <label>Поточний проксі
            <select value={proxy || ""} onChange={(e) => setProxy(e.target.value)}>
              <option value="">Без проксі</option>
              {proxies.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.host}:{item.port}</option>)}
            </select>
          </label>
          <button className="primary-button" onClick={assignProxy} disabled={busy === "proxy"}>
            {busy === "proxy" ? "Зберігаю..." : "Зберегти проксі"}
          </button>
        </div>
      )}

      {tab === "stats" && (
        <div className="details-grid">
          <div><span>Auth</span><b>{statusLabels[account.auth_state] || account.auth_state}</b></div>
          <div><span>Статус</span><b>{account.status}</b></div>
          <div><span>Health</span><b>{account.health_score}/100</b></div>
          <div><span>Живучість</span><b>{account.liveness_score ?? account.health_score}/100</b></div>
          <div><span>Ризик</span><b>{accountRiskLabel(account.risk_level)}</b></div>
          <div><span>Підключений</span><b>{account.is_attached ? "так" : "ні"}</b></div>
          <div><span>Дата народження</span><b>{profile.birth_date || account.birth_date || "не задано"}</b></div>
          <div><span>Роль</span><b>{account.role || "без ролі"}</b></div>
          <div><span>Session</span><b>{account.session_name}</b></div>
          <div><span>Source</span><b>{account.source}</b></div>
        </div>
      )}

      {tab === "actions" && (
        <div className="modal-grid">
          <div className="details-actions">
            <button onClick={loadHealth} disabled={busy === "health"}>{busy === "health" ? "Перевіряю..." : "Перевірити стан"}</button>
            <button onClick={() => recordAction("success", "manual-check")} disabled={!!busy}>Позначити успішну дію</button>
            <button onClick={spamCheck} disabled={busy === "spam-check"}>{busy === "spam-check" ? "Перевіряю..." : "Перевірити спамблок"}</button>
            <button onClick={exportSession} disabled={busy === "export-session"}>{busy === "export-session" ? "Експорт..." : "Експорт session"}</button>
            <button onClick={() => setTab("profile")}>Редагувати профіль</button>
            <button onClick={deleteAccount} disabled={busy === "delete"} className="danger-button">
              {busy === "delete" ? "Видаляю..." : "Повністю видалити"}
            </button>
          </div>
          <small>Дії пишуться в health/runtime історію акаунта та одразу оновлюють таблицю.</small>
        </div>
      )}

      {tab === "health" && (
        <div className="modal-grid">
          <button className="primary-button" onClick={loadHealth} disabled={busy === "health"}>
            {busy === "health" ? "Оновлюю..." : "Оновити health"}
          </button>
          <div className="details-grid">
            <div><span>Score</span><b>{health?.health_score ?? account.health_score}</b></div>
            <div><span>Живучість</span><b>{health?.liveness_score ?? account.liveness_score ?? account.health_score}/100</b></div>
            <div><span>Ризик</span><b>{accountRiskLabel(health?.risk_level ?? account.risk_level)}</b></div>
            <div><span>Карантин</span><b>{health?.quarantine_until || account.quarantine_until || "немає"}</b></div>
            <div><span>Останній успіх</span><b>{health?.last_success_at || account.last_success_at || "немає"}</b></div>
            <div><span>Остання помилка</span><b>{health?.last_error_at || account.last_error_at || "немає"}</b></div>
            <div><span>Sleep</span><b>{account.sleep_min_seconds}-{account.sleep_max_seconds}s</b></div>
            <div><span>Last auth error</span><b>{health?.last_auth_error || account.last_auth_error || "немає"}</b></div>
          </div>
          <div className="event-list">
            {(health?.recent_events || []).map((event) => (
              <div key={event.id}>
                <b>{event.event_type}</b>
                <span>{event.score_delta > 0 ? "+" : ""}{event.score_delta}</span>
                <small>{event.created_at}</small>
              </div>
            ))}
            {health && !health.recent_events?.length && <div className="empty-state">Health подій ще немає.</div>}
          </div>
        </div>
      )}
    </Modal>
  );
}

function AccountTelegramWebModal({ account, onClose, onSaved }) {
  const [dialogs, setDialogs] = useState([]);
  const [selectedDialog, setSelectedDialog] = useState(null);
  const [messages, setMessages] = useState([]);
  const [query, setQuery] = useState("");
  const [messageText, setMessageText] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState("dialogs");

  async function loadDialogs() {
    setError("");
    setNotice("");
    setLoading("dialogs");
    try {
      const payload = await apiFetch(`/api/v1/accounts/telegram-accounts/${account.id}/dialogs/?limit=60`);
      const nextDialogs = payload.dialogs || [];
      setDialogs(nextDialogs);
      if (!selectedDialog && nextDialogs.length) {
        setSelectedDialog(nextDialogs[0]);
      }
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setLoading("");
    }
  }

  async function loadMessages(dialog = selectedDialog) {
    if (!dialog) return;
    setError("");
    setLoading("messages");
    try {
      const params = new URLSearchParams({ chat_id: dialog.id, limit: "80" });
      const payload = await apiFetch(`/api/v1/accounts/telegram-accounts/${account.id}/messages/?${params.toString()}`);
      setSelectedDialog(payload.chat || dialog);
      setMessages(payload.messages || []);
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setLoading("");
    }
  }

  async function sendMessage(event) {
    event.preventDefault();
    if (!selectedDialog || !messageText.trim()) return;
    setError("");
    setNotice("");
    setLoading("send");
    try {
      const payload = await apiFetch(`/api/v1/accounts/telegram-accounts/${account.id}/send-message/`, {
        method: "POST",
        body: { chat_id: selectedDialog.id, text: messageText },
      });
      setMessages((items) => [...items, payload.message]);
      setMessageText("");
      setNotice("Повідомлення відправлено.");
      await onSaved();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setLoading("");
    }
  }

  useEffect(() => {
    loadDialogs();
  }, []);

  useEffect(() => {
    if (selectedDialog) loadMessages(selectedDialog);
  }, [selectedDialog?.id]);

  const filteredDialogs = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return dialogs;
    return dialogs.filter((dialog) => {
      const haystack = [dialog.title, dialog.username, dialog.last_message].filter(Boolean).join(" ").toLowerCase();
      return haystack.includes(needle);
    });
  }, [dialogs, query]);

  return (
    <Modal title={`Telegram Web · ${accountName(account)}`} onClose={onClose} wide>
      <div className="telegram-web-shell">
        <aside className="dialog-pane">
          <div className="chat-toolbar">
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Пошук чатів..." />
            <button onClick={loadDialogs} disabled={loading === "dialogs"}>{loading === "dialogs" ? "…" : "↻"}</button>
          </div>
          <div className="dialog-list">
            {filteredDialogs.map((dialog) => (
              <button
                key={dialog.id}
                className={selectedDialog?.id === dialog.id ? "active" : ""}
                onClick={() => setSelectedDialog(dialog)}
              >
                <span className="dialog-avatar">{(dialog.title || "?").slice(0, 1).toUpperCase()}</span>
                <span>
                  <b>{dialog.title || dialog.username || dialog.id}</b>
                  <small>{dialog.last_message || dialog.type}</small>
                </span>
                <em>
                  {dialog.unread_count ? <strong>{dialog.unread_count}</strong> : null}
                  {compactDate(dialog.last_message_date)}
                </em>
              </button>
            ))}
            {!filteredDialogs.length && <div className="empty-state">Чатів не знайдено.</div>}
          </div>
        </aside>

        <section className="message-pane">
          <header className="message-header">
            <div>
              <b>{selectedDialog?.title || "Оберіть чат"}</b>
              <small>{selectedDialog?.username ? `@${selectedDialog.username}` : selectedDialog?.type || "dialog"}</small>
            </div>
            <button onClick={() => loadMessages()} disabled={!selectedDialog || loading === "messages"}>
              {loading === "messages" ? "Оновлюю..." : "Оновити"}
            </button>
          </header>

          {error && <div className="alert error">{error}</div>}
          {notice && <div className="alert success">{notice}</div>}

          <div className="message-list">
            {messages.map((message, index) => (
              <div key={`${message.id || "message"}-${message.date || index}`} className={`message-bubble ${message.outgoing ? "outgoing" : ""}`}>
                {!message.outgoing && <strong>{message.sender || selectedDialog?.title || "chat"}</strong>}
                <p>{message.text || (message.media ? "[media]" : "")}</p>
                <small>{compactDate(message.date)}</small>
              </div>
            ))}
            {!messages.length && selectedDialog && <div className="empty-state">Історії повідомлень ще немає.</div>}
            {!selectedDialog && <div className="empty-state">Оберіть чат зліва.</div>}
          </div>

          <form className="chat-composer" onSubmit={sendMessage}>
            <textarea
              value={messageText}
              onChange={(e) => setMessageText(e.target.value.slice(0, 4096))}
              placeholder="Написати повідомлення..."
              disabled={!selectedDialog}
            />
            <button className="primary-button" disabled={!selectedDialog || !messageText.trim() || loading === "send"}>
              {loading === "send" ? "Відправляю..." : "Відправити"}
            </button>
          </form>
        </section>
      </div>
    </Modal>
  );
}

export default function AccountManagerPage() {
  const [overview, setOverview] = useState(emptyOverview);
  const [roleTemplates, setRoleTemplates] = useState([]);
  const [me, setMe] = useState(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState([]);
  const [modal, setModal] = useState(null);
  const [activeAccount, setActiveAccount] = useState(null);
  const [chatAccount, setChatAccount] = useState(null);
  const [reauthAccount, setReauthAccount] = useState(null);
  const [twoFaAccounts, setTwoFaAccounts] = useState([]);
  const [channelAccounts, setChannelAccounts] = useState([]);
  const [detailsTab, setDetailsTab] = useState("profile");
  const [openMenu, setOpenMenu] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const user = await apiFetch("/api/v1/auth/me/");
      const nextOverview = await apiFetch("/api/v1/accounts/overview/");
      const templates = await apiFetch("/api/v1/accounts/role-templates/");
      setOverview(nextOverview);
      setRoleTemplates(templates);
      setMe(user);
    } catch (exc) {
      if (exc instanceof Error && exc.message === "AUTH_REQUIRED") {
        window.location.replace("/auth");
        return;
      }
      setError(normalizeApiError(exc));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const accounts = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return overview.accounts;
    return overview.accounts.filter((account) => {
      const haystack = [account.label, account.phone_number, account.telegram_username, account.first_name, account.last_name]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [overview.accounts, query]);

  const counts = {
    active: overview.accounts.filter((a) => a.is_attached).length,
    working: overview.connected_count,
    quarantined: overview.quarantined_count,
    banned: overview.accounts.filter((a) => a.status === "banned").length,
    frozen: overview.accounts.filter((a) => a.status === "draft").length,
    reauth: overview.accounts.filter((a) => a.auth_state === "failed").length,
  };

  async function detachSelected() {
    if (!selected.length) return;
    setError("");
    setNotice("");
    setBusyAction("detach-selected");
    try {
      await apiFetch("/api/v1/accounts/detach/", { method: "POST", body: { account_ids: selected } });
      setSelected([]);
      setNotice("Вибрані акаунти відв'язано.");
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusyAction("");
    }
  }

  async function patchAccounts(ids, payload, successText) {
    if (!ids.length) return;
    setError("");
    setNotice("");
    setBusyAction(successText);
    try {
      for (const id of ids) {
        await apiFetch(`/api/v1/accounts/telegram-accounts/${id}/`, { method: "PATCH", body: payload });
      }
      setNotice(successText);
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusyAction("");
    }
  }

  async function checkAccounts(ids) {
    if (!ids.length) return;
    setError("");
    setNotice("");
    setBusyAction("check-accounts");
    try {
      for (const id of ids) {
        await apiFetch(`/api/v1/accounts/${id}/health/`);
      }
      setNotice("Перевірку акаунтів виконано.");
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusyAction("");
    }
  }

  async function checkSelectedProxies() {
    setError("");
    setNotice("");
    setBusyAction("check-proxies");
    try {
      const picked = overview.accounts.filter((account) => selected.includes(account.id));
      if (!picked.length) throw new Error("У вибраних акаунтів немає призначених проксі.");
      for (const account of picked) {
        await apiFetch(`/api/v1/accounts/telegram-accounts/${account.id}/proxy-check/`, { method: "POST", body: {} });
      }
      setNotice("Перевірку проксі запущено.");
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusyAction("");
    }
  }

  async function checkProxyAccount(account) {
    setOpenMenu(null);
    setError("");
    setNotice("");
    setBusyAction(`proxy-${account.id}`);
    try {
      const result = await apiFetch(`/api/v1/accounts/telegram-accounts/${account.id}/proxy-check/`, { method: "POST", body: {} });
      setNotice(`${accountName(account)}: проксі працює${result.latency_ms ? ` · ${result.latency_ms}ms` : ""}.`);
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusyAction("");
    }
  }

  async function deleteAccount(account) {
    if (!window.confirm(`Повністю видалити акаунт "${accountName(account)}"?`)) return;
    setError("");
    setNotice("");
    setBusyAction(`delete-${account.id}`);
    try {
      await apiFetch(`/api/v1/accounts/telegram-accounts/${account.id}/`, { method: "DELETE" });
      setSelected((items) => items.filter((id) => id !== account.id));
      setNotice("Акаунт повністю видалено.");
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusyAction("");
    }
  }

  async function spamCheckAccount(account) {
    setOpenMenu(null);
    setError("");
    setNotice("");
    setBusyAction(`spam-${account.id}`);
    try {
      const result = await apiFetch(`/api/v1/accounts/telegram-accounts/${account.id}/spam-check/`, { method: "POST", body: {} });
      setNotice(result.limited ? `${accountName(account)}: є обмеження SpamBot.` : `${accountName(account)}: спамблок не виявлено.`);
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusyAction("");
    }
  }

  async function resendCode(account) {
    setOpenMenu(null);
    setError("");
    setNotice("");
    setBusyAction(`reauth-${account.id}`);
    try {
      const updated = await apiFetch(`/api/v1/accounts/${account.id}/resend-code/`, { method: "POST", body: {} });
      setReauthAccount(updated);
      setModal("reauth");
      setNotice(`${accountName(account)}: код переавторизації запрошено.`);
      await load();
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusyAction("");
    }
  }

  async function downloadSession(account) {
    setOpenMenu(null);
    setError("");
    setNotice("");
    setBusyAction(`export-${account.id}`);
    try {
      const { access } = authTokens();
      const response = await fetch(backendApiUrl(`/api/v1/accounts/telegram-accounts/${account.id}/export-session/`), {
        headers: access ? { Authorization: `Bearer ${access}` } : {},
      });
      if (!response.ok) throw new Error(await response.text());
      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = `${account.session_name}.session`;
      link.click();
      URL.revokeObjectURL(href);
      setNotice(`${accountName(account)}: session експортовано.`);
    } catch (exc) {
      setError(normalizeApiError(exc));
    } finally {
      setBusyAction("");
    }
  }

  function openDetails(account, tab = "profile") {
    setActiveAccount(account);
    setDetailsTab(tab);
    setModal("details");
  }

  function openTelegramWeb(account) {
    setOpenMenu(null);
    setChatAccount(account);
    setModal("telegram-web");
  }

  function selectedAccounts() {
    return overview.accounts.filter((account) => selected.includes(account.id));
  }

  return (
    <AppShell userLabel={me?.email || me?.full_name}>
      <section className="stats-grid">
        <StatCard icon="♙" label="Active" value={counts.active} tone="green" />
        <StatCard icon="◔" label="Working" value={counts.working} tone="blue" />
        <StatCard icon="◇" label="Quarantined" value={counts.quarantined} tone="pink" />
        <StatCard icon="♧" label="Banned" value={counts.banned} tone="red" />
        <StatCard icon="↯" label="Frozen" value={counts.frozen} tone="violet" />
        <StatCard icon="⌕" label="Reauthorization" value={counts.reauth} tone="orange" />
      </section>

      <section className="action-ribbon">
        <button onClick={() => setModal("import")} className="outline-button violet">＋ Import Accounts</button>
        <button onClick={() => setModal("add")} className="outline-button blue">♙ Add Account</button>
        <button onClick={() => setModal("proxy")} className="outline-button green">▤ Proxy Pool</button>
        <button onClick={() => setModal("roles")} className="outline-button violet">✦ AI Roles</button>
      </section>

      {error && (
        <div className="alert error">
          {error.includes("credentials") || error.includes("Authentication") ? (
            <>Потрібна авторизація. <a href="/auth/">Увійти</a></>
          ) : error}
        </div>
      )}
      {notice && <div className="alert success">{notice}</div>}

      <section className="table-card">
        <div className="table-tools">
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by name, phone, username..." />
          <button className="icon-button" onClick={() => setQuery("")}>♢</button>
          <button className="ghost-button" onClick={load} disabled={loading}>{loading ? "Loading..." : "Refresh"}</button>
        </div>

        {selected.length > 0 && (
          <div className="bulk-bar">
            <span>{selected.length} вибрано</span>
            <button onClick={() => selectedAccounts()[0] && openDetails(selectedAccounts()[0], "profile")}>AI профілі</button>
            <button onClick={checkSelectedProxies} disabled={busyAction === "check-proxies"}>Перевірити проксі</button>
            <button onClick={() => checkAccounts(selected)} disabled={busyAction === "check-accounts"}>Перевірити акаунти</button>
            <button onClick={() => setModal("roles")}>AI ролі</button>
            <button onClick={() => {
              const template = roleTemplates[0];
              if (!template) {
                setModal("roles");
                return;
              }
              patchAccounts(selected, { role_template: template.id }, `Роль "${template.name}" призначено.`);
            }}>Призначити роль</button>
            <button onClick={() => { setTwoFaAccounts(selectedAccounts()); setModal("set2fa"); }}>Установити 2FA</button>
            <button onClick={() => { setChannelAccounts(selectedAccounts()); setModal("channel"); }}>Створити канал</button>
            <button onClick={() => selectedAccounts()[0] && openDetails(selectedAccounts()[0], "actions")}>Переавторизація</button>
            <button className="danger-text" onClick={detachSelected} disabled={busyAction === "detach-selected"}>Відв'язати</button>
          </div>
        )}

        <div className="accounts-table">
          <div className="account-row head">
            <input type="checkbox" checked={selected.length > 0 && selected.length === accounts.length} onChange={(e) => setSelected(e.target.checked ? accounts.map((a) => a.id) : [])} />
            <span>Avatar</span><span>Name</span><span>Role</span><span>Status</span><span>Warming</span><span>Proxy</span><span>Actions</span>
          </div>
          {accounts.map((account) => (
            <div className={`account-row ${selected.includes(account.id) ? "selected" : ""}`} key={account.id}>
              <input type="checkbox" checked={selected.includes(account.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, account.id] : selected.filter((id) => id !== account.id))} />
              <AccountAvatar account={account} />
              <span>
                <b>{accountName(account)}</b>
                <small>@{account.telegram_username || account.phone_number || account.label}</small>
              </span>
              <span>
                <b className={`badge ${operationalRoleTone(account)}`}>{operationalRoleLabel(account)}</b>
                <button className="mini-button subtle" onClick={() => {
                  if (!roleTemplates.length) {
                    setModal("roles");
                    return;
                  }
                  const options = roleTemplates.map((template) => `${template.id}: ${template.name}`).join("\n");
                  const picked = window.prompt(`ID ролі для акаунта:\n${options}`, account.role_template || roleTemplates[0].id);
                  if (picked !== null) patchAccounts([account.id], { role_template: Number(picked) || null }, "Роль акаунта оновлено.");
                }}>
                  AI: {account.role || "＋ Add"}
                </button>
              </span>
              <span>
                <b className={`badge ${accountStatusTone(account)}`}>
                  {accountStatusLabel(account)}
                </b>
              </span>
              <span>
                <b className="badge amber">{warmupAgeLabel(account)}</b>
              </span>
              <span><b className={`badge ${account.proxy ? "green" : "gray"}`}>{proxyLabel(overview.proxies, account.proxy)}</b></span>
              <span className="row-actions">
                <button
                  title="Health"
                  disabled={busyAction === `health-${account.id}`}
                  onClick={async () => {
                    setError("");
                    setNotice("");
                    setBusyAction(`health-${account.id}`);
                    try {
                      await apiFetch(`/api/v1/accounts/${account.id}/health/`);
                      setNotice(`${accountName(account)}: health оновлено.`);
                      await load();
                    } catch (exc) {
                      setError(normalizeApiError(exc));
                    } finally {
                      setBusyAction("");
                    }
                  }}
                >{busyAction === `health-${account.id}` ? "…" : "✓"}</button>
                <button title="Відкрити чати" onClick={() => openTelegramWeb(account)}>▣</button>
                <button title="Info" onClick={() => openDetails(account, "stats")}>ⓘ</button>
                <span className="menu-anchor">
                  <button title="Actions" onClick={() => setOpenMenu(openMenu === account.id ? null : account.id)}>⋮</button>
                  {openMenu === account.id && (
                    <div className="action-menu">
                      <button onClick={() => openTelegramWeb(account)}>▣ Відкрити чати</button>
                      <button onClick={() => spamCheckAccount(account)}>♡ Перевірити на спамблок</button>
                      <button onClick={() => { setOpenMenu(null); openDetails(account, "stats"); }}>ⓘ Інформація</button>
                      <button onClick={() => checkProxyAccount(account)}>▤ Перевірити проксі</button>
                      <button onClick={() => { setOpenMenu(null); openDetails(account, "profile"); }}>✎ Редагувати профіль</button>
                      <button onClick={() => { setOpenMenu(null); setChannelAccounts([account]); setModal("channel"); }}>☷ Створити канал</button>
                      <button onClick={() => { setOpenMenu(null); setTwoFaAccounts([account]); setModal("set2fa"); }}>🔐 Установити 2FA</button>
                      <button onClick={() => downloadSession(account)}>⇩ Експорт session</button>
                      <button onClick={() => resendCode(account)}>↻ Переавторизувати</button>
                      <button className="danger-text" onClick={() => deleteAccount(account)}>⌫ Видалити</button>
                    </div>
                  )}
                </span>
                <button title="Delete" className="danger-text" onClick={() => deleteAccount(account)} disabled={busyAction === `delete-${account.id}`}>×</button>
              </span>
            </div>
          ))}
          {!accounts.length && <div className="empty-state">Акаунтів ще немає.</div>}
        </div>
      </section>

      {modal === "add" && <AddAccountModal proxies={overview.proxies} onClose={() => setModal(null)} onSaved={load} />}
      {modal === "reauth" && reauthAccount && (
        <ReauthAccountModal
          initialAccount={reauthAccount}
          onClose={() => {
            setModal(null);
            setReauthAccount(null);
          }}
          onSaved={load}
        />
      )}
      {modal === "import" && <ImportAccountsModal proxies={overview.proxies} onClose={() => setModal(null)} onSaved={load} />}
      {modal === "proxy" && <ProxyPoolModal proxies={overview.proxies} onClose={() => setModal(null)} onSaved={load} />}
      {modal === "roles" && <RoleTemplatesModal templates={roleTemplates} onClose={() => setModal(null)} onSaved={load} />}
      {modal === "set2fa" && twoFaAccounts.length > 0 && (
        <Set2FAModal accounts={twoFaAccounts} onClose={() => setModal(null)} onSaved={load} />
      )}
      {modal === "channel" && channelAccounts.length > 0 && (
        <CreateChannelModal accounts={channelAccounts} onClose={() => setModal(null)} onSaved={load} />
      )}
      {modal === "details" && activeAccount && (
        <AccountDetailsModal
          account={activeAccount}
          proxies={overview.proxies}
          initialTab={detailsTab}
          onClose={() => setModal(null)}
          onSaved={load}
        />
      )}
      {modal === "telegram-web" && chatAccount && (
        <AccountTelegramWebModal
          account={chatAccount}
          onClose={() => {
            setModal(null);
            setChatAccount(null);
          }}
          onSaved={load}
        />
      )}
    </AppShell>
  );
}
