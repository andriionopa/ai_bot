(function () {
  const config = window.farmPageConfig || {};
  const csrfToken = (() => {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  })();

  const flashBox = document.getElementById("flash-box");
  const accountsTbody = document.getElementById("accounts-tbody");
  const logOutput = document.getElementById("log-output");
  const statusPill = document.getElementById("status-pill");
  const proxySelects = () => Array.from(document.querySelectorAll("[data-proxy-select]"));
  let latestOverview = null;

  function showFlash(message, tone = "info") {
    if (!flashBox) {
      return;
    }
    flashBox.hidden = false;
    flashBox.className = `flash-box flash-${tone}`;
    flashBox.textContent = message;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function stashFlash(message, tone = "info") {
    window.sessionStorage.setItem("farm_flash", JSON.stringify({message, tone}));
  }

  function restoreFlash() {
    const raw = window.sessionStorage.getItem("farm_flash");
    if (!raw) {
      return;
    }
    window.sessionStorage.removeItem("farm_flash");
    try {
      const payload = JSON.parse(raw);
      showFlash(payload.message, payload.tone);
    } catch {
      return;
    }
  }

  async function apiFetch(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: {
        "X-CSRFToken": csrfToken,
        ...(options.body instanceof FormData ? {} : {"Content-Type": "application/json"}),
        ...(options.headers || {}),
      },
      ...options,
    });

    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "string" ? payload : JSON.stringify(payload);
      throw new Error(detail);
    }
    return payload;
  }

  function renderStats(data) {
    const mapping = {
      "stat-accounts": data.account_count,
      "stat-attached": data.attached_count,
      "stat-connected": data.connected_count,
      "stat-pending": data.pending_auth_count,
      "stat-quarantine": data.quarantined_count,
      "stat-proxies": data.proxy_count,
    };
    Object.entries(mapping).forEach(([id, value]) => {
      const element = document.getElementById(id);
      if (element) {
        element.textContent = value ?? 0;
      }
    });
  }

  function renderProxyOptions(proxies) {
    if (!proxySelects().length) {
      return;
    }
    const options = ['<option value="">Без проксі</option>']
      .concat(proxies.map((proxy) => `<option value="${proxy.id}">${escapeHtml(proxy.name)} · ${escapeHtml(proxy.status)}</option>`))
      .join("");
    proxySelects().forEach((select) => {
      const currentValue = select.value;
      select.innerHTML = options;
      if (currentValue) {
        select.value = currentValue;
      }
    });
  }

  function authCodeMeta(account) {
    if (!account.auth_code_sent_at) {
      return "";
    }
    const sentAt = new Date(account.auth_code_sent_at);
    const timeout = Number(account.auth_code_timeout_seconds || 0);
    if (!timeout) {
      return `<div class="auth-hint">Код активний з ${sentAt.toLocaleTimeString()}</div>`;
    }
    const expiresAt = new Date(sentAt.getTime() + timeout * 1000);
    return `<div class="auth-hint">Код активний до ${expiresAt.toLocaleTimeString()}</div>`;
  }

  function authActionButton(account) {
    if (account.auth_state === "pending_code") {
      return `
        <div class="auth-mini" data-id="${account.id}" data-auth-state="pending_code">
          <input class="input auth-input" data-auth-code type="text" inputmode="numeric" autocomplete="one-time-code" placeholder="Код Telegram" />
          <input class="input auth-input" data-auth-password type="password" autocomplete="current-password" placeholder="2FA пароль, якщо є" />
          ${authCodeMeta(account)}
          <div class="auth-actions">
            <button class="button button-primary account-action" type="button" data-action="complete-auth" data-id="${account.id}">Підтвердити</button>
            <button class="button button-ghost account-action" type="button" data-action="resend-code" data-id="${account.id}">Новий код</button>
          </div>
        </div>
      `;
    }
    if (account.auth_state === "pending_2fa") {
      return `
        <div class="auth-mini" data-id="${account.id}" data-auth-state="pending_2fa">
          <input class="input auth-input" data-auth-password type="password" autocomplete="current-password" placeholder="2FA пароль" />
          <div class="auth-actions">
            <button class="button button-primary account-action" type="button" data-action="complete-auth" data-id="${account.id}">Підтвердити 2FA</button>
            <button class="button button-ghost account-action" type="button" data-action="resend-code" data-id="${account.id}">Новий код</button>
          </div>
        </div>
      `;
    }
    if (account.auth_state === "failed" && account.source === "credentials" && account.is_attached) {
      return `<button class="button button-ghost account-action" type="button" data-action="resend-code" data-id="${account.id}">Надіслати код знову</button>`;
    }
    return `<button class="button button-ghost account-action" type="button" data-action="health" data-id="${account.id}">Health</button>`;
  }

  function accountProxyControl(account) {
    const options = ['<option value="">Без проксі</option>']
      .concat((latestOverview?.proxies || []).map((proxy) => {
        const selected = Number(account.proxy || 0) === Number(proxy.id) ? "selected" : "";
        return `<option value="${proxy.id}" ${selected}>${escapeHtml(proxy.name)} · ${escapeHtml(proxy.status)}</option>`;
      }))
      .join("");
    return `
      <div class="proxy-mini" data-id="${account.id}">
        <select class="input proxy-input" data-account-proxy>
          ${options}
        </select>
        <button class="button button-ghost account-action" type="button" data-action="assign-proxy" data-id="${account.id}">Зберегти</button>
      </div>
    `;
  }

  function renderAccounts(accounts) {
    if (!accountsTbody) {
      return;
    }
    if (!accounts.length) {
      accountsTbody.innerHTML = `<tr><td colspan="8" class="empty-state">Поки немає підв’язаних акаунтів.</td></tr>`;
      return;
    }

    accountsTbody.innerHTML = accounts.map((account) => {
      const quarantine = account.quarantine_until ? `<div class="meta">${escapeHtml(account.quarantine_until)}</div>` : "";
      return `
        <tr>
          <td><input class="row-check" type="checkbox" value="${account.id}" ${account.is_attached ? "" : "disabled"} /></td>
          <td>
            <strong>${escapeHtml(account.label)}</strong>
            <div class="meta">${escapeHtml(account.phone_number || account.session_name)}</div>
          </td>
          <td><span class="pill pill-inline">${escapeHtml(account.source)}</span></td>
          <td>
            <span class="state-chip state-${escapeHtml(account.auth_state)}">${escapeHtml(account.auth_state)}</span>
            ${account.last_auth_error ? `<div class="meta meta-danger">${escapeHtml(account.last_auth_error)}</div>` : ""}
          </td>
          <td>
            <span class="state-chip state-${escapeHtml(account.status)}">${escapeHtml(account.status)}</span>
            ${quarantine}
          </td>
          <td>${escapeHtml(account.health_score)}</td>
          <td>${accountProxyControl(account)}</td>
          <td class="actions-cell">${authActionButton(account)}</td>
        </tr>
      `;
    }).join("");
  }

  async function fetchOverview() {
    if (!config.overviewUrl) {
      return null;
    }
    const data = await apiFetch(config.overviewUrl, {method: "GET"});
    latestOverview = data;
    renderStats(data);
    renderProxyOptions(data.proxies || []);
    renderAccounts(data.accounts || []);
    return data;
  }

  async function submitSessionAttach(form) {
    const formData = new FormData(form);
    await apiFetch(config.addUrl, {method: "POST", body: formData});
    form.reset();
    showFlash("Session акаунт підв’язано до ферми.");
    await fetchOverview();
  }

  async function submitCredentialsAttach(form) {
    const formData = new FormData(form);
    const result = await apiFetch(config.addUrl, {method: "POST", body: formData});
    form.reset();
    if (result.auth_state === "pending_code") {
      stashFlash("Код входу відправлено в Telegram. Введи його на сторінці статусів.");
      window.location.href = config.statusPageUrl;
      return;
    }
    showFlash(result.last_auth_error || "Не вдалося відправити код входу.", "danger");
    await fetchOverview();
  }

  async function submitProxy(form) {
    const formData = new FormData(form);
    const payload = Object.fromEntries(formData.entries());
    payload.port = Number(payload.port);
    await apiFetch(config.proxyAddUrl, {method: "POST", body: JSON.stringify(payload)});
    form.reset();
    showFlash("Проксі збережено.");
    await fetchOverview();
  }

  function selectedAccountIds() {
    return Array.from(document.querySelectorAll(".row-check:checked")).map((checkbox) => Number(checkbox.value));
  }

  async function detachSelected() {
    const accountIds = selectedAccountIds();
    if (!accountIds.length) {
      showFlash("Спочатку вибери хоча б один акаунт.", "warning");
      return;
    }
    await apiFetch(config.detachUrl, {
      method: "POST",
      body: JSON.stringify({account_ids: accountIds}),
    });
    showFlash("Вибрані акаунти відв’язані від ферми.", "warning");
    await fetchOverview();
  }

  async function cleanupStale() {
    if (!window.confirm("Повністю видалити failed/detached профілі та їх session-файли?")) {
      return;
    }
    const payload = await apiFetch(config.cleanupStaleUrl, {
      method: "POST",
      body: JSON.stringify({}),
    });
    showFlash(`Очищено завислих профілів: ${payload.deleted_count}.`, "warning");
    await fetchOverview();
  }

  async function completeAuth(button) {
    const authMini = button.closest(".auth-mini");
    const accountId = button.dataset.id;
    const authState = authMini?.dataset.authState || "";
    let code = "";
    if (authState === "pending_code") {
      code = authMini?.querySelector("[data-auth-code]")?.value.trim() || "";
      if (!code) {
        showFlash("Код не введено. Якщо код протух, натисни 'Новий код'.", "warning");
        return;
      }
    }
    const password = authMini?.querySelector("[data-auth-password]")?.value || "";
    const payload = await apiFetch(`/api/v1/accounts/${accountId}/complete-auth/`, {
      method: "POST",
      body: JSON.stringify({verification_code: code, password_2fa: password}),
    });
    if (payload.auth_state === "connected") {
      showFlash("Акаунт підключено до ферми.");
    } else if (payload.auth_state === "pending_2fa") {
      showFlash("Telegram прийняв код і запросив 2FA пароль. Введи 2FA у цьому ж рядку.", "warning");
    } else {
      showFlash(payload.last_auth_error || "Auth state оновлено.", payload.auth_state === "failed" ? "danger" : "info");
    }
    await fetchOverview();
  }

  async function resendCode(accountId) {
    const payload = await apiFetch(`/api/v1/accounts/${accountId}/resend-code/`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (payload.auth_state === "pending_code") {
      showFlash("Новий код входу відправлено.");
    } else {
      showFlash(payload.last_auth_error || "Не вдалося повторно надіслати код.", "danger");
    }
    await fetchOverview();
  }

  async function assignProxy(button) {
    const proxyMini = button.closest(".proxy-mini");
    const accountId = button.dataset.id;
    const selected = proxyMini?.querySelector("[data-account-proxy]")?.value || "";
    const payload = await apiFetch(`/api/v1/accounts/${accountId}/proxy/`, {
      method: "POST",
      body: JSON.stringify({proxy: selected ? Number(selected) : null}),
    });
    showFlash(`${payload.label}: проксі оновлено.`);
    await fetchOverview();
  }

  async function showHealth(accountId) {
    const data = await apiFetch(`/api/v1/accounts/${accountId}/health/`, {method: "GET"});
    const events = data.recent_events.map((event) => `${event.event_type} (${event.score_delta})`).join(", ") || "без подій";
    showFlash(`Health ${data.label}: ${data.health_score}, статус ${data.status}, події: ${events}`);
  }

  function bindForms() {
    const sessionForm = document.getElementById("session-attach-form");
    if (sessionForm) {
      sessionForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          await submitSessionAttach(sessionForm);
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }

    const credentialsForm = document.getElementById("credentials-attach-form");
    if (credentialsForm) {
      credentialsForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          await submitCredentialsAttach(credentialsForm);
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }

    const proxyForm = document.getElementById("proxy-form");
    if (proxyForm) {
      proxyForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          await submitProxy(proxyForm);
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }
  }

  function bindStatusControls() {
    const detachButton = document.getElementById("detach-selected");
    if (detachButton) {
      detachButton.addEventListener("click", async () => {
        try {
          await detachSelected();
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }

    const refreshButton = document.getElementById("refresh-overview");
    if (refreshButton) {
      refreshButton.addEventListener("click", async () => {
        try {
          await fetchOverview();
          showFlash("Зведення оновлено.");
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }

    const cleanupButton = document.getElementById("cleanup-stale");
    if (cleanupButton) {
      cleanupButton.addEventListener("click", async () => {
        try {
          await cleanupStale();
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }

    const selectAll = document.getElementById("select-all");
    if (selectAll) {
      selectAll.addEventListener("change", (event) => {
        document.querySelectorAll(".row-check:not(:disabled)").forEach((checkbox) => {
          checkbox.checked = event.currentTarget.checked;
        });
      });
    }

    if (accountsTbody) {
      accountsTbody.addEventListener("click", async (event) => {
        const button = event.target.closest(".account-action");
        if (!button) {
          return;
        }
        try {
          if (button.dataset.action === "complete-auth") {
            await completeAuth(button);
          } else if (button.dataset.action === "resend-code") {
            await resendCode(button.dataset.id);
          } else if (button.dataset.action === "assign-proxy") {
            await assignProxy(button);
          } else if (button.dataset.action === "health") {
            await showHealth(button.dataset.id);
          }
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }
  }

  function bindLogStream() {
    if (!config.websocketUrl || !logOutput || !statusPill) {
      return;
    }
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${window.location.host}${config.websocketUrl}`);

    socket.onopen = () => {
      statusPill.textContent = "online";
      statusPill.className = "pill pill-online";
      logOutput.textContent = "Підключено до лог-потоку.\n";
    };

    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      logOutput.textContent += `${new Date().toISOString()} ${payload.level || "info"} ${payload.source || "system"}: ${payload.message || ""}\n`;
      logOutput.scrollTop = logOutput.scrollHeight;
    };

    socket.onclose = () => {
      statusPill.textContent = "offline";
      statusPill.className = "pill pill-offline";
      logOutput.textContent += "\nПотік логів закрито.";
    };
  }

  restoreFlash();
  bindForms();
  bindStatusControls();
  bindLogStream();
  fetchOverview().catch((error) => {
    showFlash(error.message, "danger");
  });
})();
