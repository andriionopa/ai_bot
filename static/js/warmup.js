(function () {
  const config = window.warmupPageConfig || {};
  const csrfToken = (() => {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  })();

  const flashBox = document.getElementById("flash-box");
  const policySelect = document.getElementById("warmup-policy-select");
  const targetSelect = document.getElementById("warmup-target-select");
  const accountSelect = document.getElementById("warmup-account-select");
  const plansTbody = document.getElementById("warmup-plans-tbody");
  const actionsTbody = document.getElementById("warmup-actions-tbody");
  const warmupConsole = document.getElementById("warmup-console");
  const accountRecommendations = document.getElementById("warmup-account-recommendations");
  const targetPreviewList = document.getElementById("target-preview-list");
  const logSearch = document.getElementById("warmup-log-search");
  let latestOverview = null;
  let latestAccountsOverview = null;
  let latestLogs = [];
  let activeLogFilter = "all";

  function showFlash(message, tone = "info") {
    if (!flashBox) return;
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
      throw new Error(typeof payload === "string" ? payload : JSON.stringify(payload));
    }
    return payload;
  }

  function formPayload(form) {
    const data = Object.fromEntries(new FormData(form).entries());
    form.querySelectorAll("input[type='number']").forEach((input) => {
      data[input.name] = Number(input.value);
    });
    form.querySelectorAll("input[type='checkbox']").forEach((input) => {
      data[input.name] = input.checked;
    });
    return data;
  }

  function selectedValues(select) {
    if (!select) return [];
    return Array.from(select.selectedOptions).map((option) => Number(option.value));
  }

  function renderStats(data) {
    const mapping = {
      "warmup-connected": data.connected_accounts,
      "warmup-running": data.running_plans,
      "warmup-queued": data.queued_actions,
      "warmup-quarantine": data.quarantined_accounts,
    };
    Object.entries(mapping).forEach(([id, value]) => {
      const element = document.getElementById(id);
      if (element) element.textContent = value ?? 0;
    });
  }

  function renderSelects(data, accountsOverview) {
    if (policySelect) {
      policySelect.innerHTML = (data.policies || [])
        .filter((policy) => policy.is_active)
        .map((policy) => `<option value="${policy.id}">${escapeHtml(policy.name)}</option>`)
        .join("");
    }
    if (targetSelect) {
      targetSelect.innerHTML = (data.targets || [])
        .filter((target) => target.status === "active")
        .map((target) => `<option value="${target.id}">${escapeHtml(target.title)}</option>`)
        .join("");
    }
    if (accountSelect) {
      accountSelect.innerHTML = (accountsOverview?.accounts || [])
        .filter((account) => account.is_attached && account.auth_state === "connected")
        .map((account) => `<option value="${account.id}">${escapeHtml(account.label)} · ${escapeHtml(account.health_score)}% · ${escapeHtml(account.telegram_username || account.phone_number || "")}</option>`)
        .join("");
    }
    renderAccountSummary(accountsOverview?.accounts || []);
    renderAccountRecommendations(accountsOverview?.accounts || []);
    renderTargetPreview(data.targets || []);
  }

  function accountWarmReason(account) {
    if (account.status === "quarantine" || account.auth_state !== "connected" || !account.is_attached) return "";
    if ((account.health_score || 0) < 85) return "низький health, треба мʼякий прогрів";
    if (!account.last_success_at) return "немає успішної активності";
    return "готовий для підтримки активності";
  }

  function recommendedAccounts(accounts) {
    return accounts.filter((account) => accountWarmReason(account)).slice(0, 20);
  }

  function renderAccountSummary(accounts) {
    const total = document.getElementById("accounts-total-ui");
    const valid = document.getElementById("accounts-valid-ui");
    const selected = document.getElementById("accounts-selected-ui");
    if (total) total.textContent = accounts.length;
    if (valid) valid.textContent = accounts.filter((account) => account.is_attached && account.auth_state === "connected").length;
    if (selected) selected.textContent = selectedValues(accountSelect).length;
  }

  function renderAccountRecommendations(accounts) {
    if (!accountRecommendations) return;
    const items = recommendedAccounts(accounts);
    if (!items.length) {
      accountRecommendations.innerHTML = `<div class="empty-state">Немає акаунтів для прогріву.</div>`;
      return;
    }
    accountRecommendations.innerHTML = items.map((account) => `
      <button class="recommendation-card" type="button" data-account-id="${account.id}">
        <strong>${escapeHtml(account.label)}</strong>
        <span>${escapeHtml(accountWarmReason(account))}</span>
        <em>${escapeHtml(account.health_score)}% health</em>
      </button>
    `).join("");
  }

  function renderTargetPreview(targets) {
    if (!targetPreviewList) return;
    const activeTargets = targets.filter((target) => target.status === "active").slice(0, 8);
    if (!activeTargets.length) {
      targetPreviewList.innerHTML = `<div class="empty-state">Цілі ще не вибрані. Акаунт буде вступати у випадкові групи з плану.</div>`;
      return;
    }
    targetPreviewList.innerHTML = activeTargets.map((target) => `
      <span class="target-chip">${escapeHtml(target.target_type === "folder" ? "📁" : "📍")} ${escapeHtml(target.title)}</span>
    `).join("");
  }

  function statusLabel(status) {
    const labels = {
      draft: "Чернетка",
      running: "Активний",
      paused: "Зупинено",
      completed: "Завершено",
      queued: "Очікує",
      succeeded: "Готово",
      failed: "Помилка",
      skipped: "Пропущено",
    };
    return labels[status] || status;
  }

  function renderPlans(plans) {
    if (!plansTbody) return;
    if (!plans.length) {
      plansTbody.innerHTML = `<tr><td colspan="5" class="empty-state">Планів ще немає.</td></tr>`;
      return;
    }
    plansTbody.innerHTML = plans.map((plan) => `
      <tr>
        <td><strong>${escapeHtml(plan.name)}</strong><div class="meta">${plan.account_count} акаунт(ів), ${plan.target_count} цілей</div></td>
        <td>${escapeHtml(plan.policy_name)}</td>
        <td><span class="state-chip state-${escapeHtml(plan.status)}">${escapeHtml(statusLabel(plan.status))}</span></td>
        <td>
          <div class="meta">Очікує: ${escapeHtml(plan.queued_count)}</div>
          <div class="meta">Готово: ${escapeHtml(plan.succeeded_count)} · Помилки: ${escapeHtml(plan.failed_count)} · Пропущено: ${escapeHtml(plan.skipped_count)}</div>
        </td>
        <td class="actions-cell">
          <button class="button button-primary warmup-plan-action" data-action="start" data-id="${plan.id}" type="button">Старт</button>
          <button class="button button-ghost warmup-plan-action" data-action="pause" data-id="${plan.id}" type="button">Стоп</button>
        </td>
      </tr>
    `).join("");
  }

  function renderActions(actions) {
    if (!actionsTbody) return;
    if (!actions.length) {
      actionsTbody.innerHTML = `<div class="empty-state">Дій ще немає.</div>`;
      return;
    }
    actionsTbody.innerHTML = actions.map((action) => `
      <article class="activity-item activity-${escapeHtml(action.status)}">
        <div class="activity-icon">${escapeHtml(action.action_emoji || "•")}</div>
        <div class="activity-main">
          <div class="activity-title">
            <strong>${escapeHtml(action.account_label)}</strong>
            <span>${escapeHtml(action.action_label || action.action_type)}</span>
            <span class="state-chip state-${escapeHtml(action.status)}">${escapeHtml(statusLabel(action.status))}</span>
          </div>
          <div class="activity-meta">
            ${escapeHtml(action.target_title)} · ${new Date(action.scheduled_for).toLocaleString()}
            ${action.plan_name ? ` · ${escapeHtml(action.plan_name)}` : ""}
          </div>
          ${action.error ? `<div class="meta meta-danger">${escapeHtml(action.error)}</div>` : ""}
        </div>
      </article>
    `).join("");
  }

  function renderConsole(logs) {
    if (!warmupConsole) return;
    latestLogs = logs || [];
    renderLogCounts(latestLogs);
    const query = (logSearch?.value || "").trim().toLowerCase();
    const filteredLogs = latestLogs.filter((log) => {
      const matchesLevel = activeLogFilter === "all" || log.level === activeLogFilter;
      const text = `${log.message || ""} ${log.account_label || ""} ${log.action_type || ""}`.toLowerCase();
      return matchesLevel && (!query || text.includes(query));
    });
    if (!filteredLogs.length) {
      warmupConsole.textContent = "Логів прогріву ще немає.";
      return;
    }
    warmupConsole.textContent = filteredLogs
      .slice()
      .reverse()
      .map((log) => {
        const at = new Date(log.created_at).toLocaleTimeString();
        const icon = log.level === "success" ? "✓ УСПІХ" : log.level === "error" ? "✕ ПОМИЛКА" : log.level === "warning" ? "△ УВАГА" : "● ІНФО";
        const account = log.account_label || log.account || "-";
        return `${at}  ${icon.padEnd(12)} ${String(account).padEnd(18)} ${log.message}`;
      })
      .join("\n");
    warmupConsole.scrollTop = warmupConsole.scrollHeight;
  }

  function renderLogCounts(logs) {
    const counts = {
      all: logs.length,
      info: logs.filter((log) => log.level === "info").length,
      success: logs.filter((log) => log.level === "success").length,
      warning: logs.filter((log) => log.level === "warning").length,
      error: logs.filter((log) => log.level === "error").length,
    };
    Object.entries(counts).forEach(([key, value]) => {
      const element = document.getElementById(`log-count-${key}`);
      if (element) element.textContent = value;
    });
  }

  async function refreshWarmup() {
    const [overview, accountsOverview] = await Promise.all([
      apiFetch(config.overviewUrl, {method: "GET"}),
      apiFetch(config.accountsOverviewUrl, {method: "GET"}),
    ]);
    latestOverview = overview;
    latestAccountsOverview = accountsOverview;
    renderStats(overview);
    renderSelects(overview, accountsOverview);
    renderPlans(overview.plans || []);
    renderActions(overview.actions || []);
    renderConsole(overview.logs || []);
    return overview;
  }

  function bindForms() {
    const policyForm = document.getElementById("warmup-policy-form");
    if (policyForm) {
      policyForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          await apiFetch(config.policyAddUrl, {method: "POST", body: JSON.stringify(formPayload(policyForm))});
          policyForm.reset();
          showFlash("Сценарій прогріву збережено.");
          await refreshWarmup();
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }

    const targetForm = document.getElementById("warmup-target-form");
    if (targetForm) {
      targetForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          await apiFetch(config.targetAddUrl, {method: "POST", body: JSON.stringify(formPayload(targetForm))});
          targetForm.reset();
          showFlash("Ціль додано.");
          await refreshWarmup();
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }

    const bulkTargetForm = document.getElementById("warmup-target-bulk-form");
    if (bulkTargetForm) {
      bulkTargetForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          const payload = formPayload(bulkTargetForm);
          const result = await apiFetch(config.targetBulkImportUrl, {method: "POST", body: JSON.stringify(payload)});
          bulkTargetForm.reset();
          showFlash(`Імпортовано цілей: ${result.created_count}, пропущено дублі: ${result.skipped_count}.`);
          await refreshWarmup();
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }

    const planForm = document.getElementById("warmup-plan-form");
    if (planForm) {
      planForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          const payload = formPayload(planForm);
          payload.policy = Number(payload.policy);
          payload.account_ids = selectedValues(accountSelect);
          payload.target_ids = selectedValues(targetSelect);
          await apiFetch(config.planAddUrl, {method: "POST", body: JSON.stringify(payload)});
          planForm.reset();
          showFlash("План створено. Натисни Старт, щоб акаунти почали прогрів.");
          await refreshWarmup();
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }

    if (accountSelect) {
      accountSelect.addEventListener("change", () => renderAccountSummary(latestAccountsOverview?.accounts || []));
    }
  }

  function bindControls() {
    const refreshButton = document.getElementById("refresh-warmup");
    if (refreshButton) {
      refreshButton.addEventListener("click", async () => {
        try {
          await refreshWarmup();
          showFlash("Прогрів оновлено.");
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }

    const clearQueuedButton = document.getElementById("clear-queued-warmup");
    if (clearQueuedButton) {
      clearQueuedButton.addEventListener("click", async () => {
        try {
          const result = await apiFetch(config.actionClearUrl, {
            method: "POST",
            body: JSON.stringify({mode: "queued", clear_logs: false, purge_redis: true}),
          });
          showFlash(`Очікування очищено: ${result.deleted}.`, "warning");
          await refreshWarmup();
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }

    const clearAllButton = document.getElementById("clear-all-warmup");
    if (clearAllButton) {
      clearAllButton.addEventListener("click", async () => {
        if (!window.confirm("Очистити всю історію прогріву та зупинити старі заплановані дії?")) {
          return;
        }
        try {
          const result = await apiFetch(config.actionClearUrl, {
            method: "POST",
            body: JSON.stringify({mode: "all", clear_logs: true, purge_redis: true}),
          });
          showFlash(`Історію очищено: ${result.deleted} дій, ${result.deleted_logs} логів.`, "warning");
          await refreshWarmup();
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }

    if (plansTbody) {
      plansTbody.addEventListener("click", async (event) => {
        const button = event.target.closest(".warmup-plan-action");
        if (!button) return;
        try {
          await apiFetch(`/api/v1/warmup/plans/${button.dataset.id}/${button.dataset.action}/`, {
            method: "POST",
            body: JSON.stringify({}),
          });
          showFlash(button.dataset.action === "start" ? "План запущено. Прогрів працюватиме до Стоп." : "План зупинено.");
          await refreshWarmup();
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }

    const autoPickButton = document.getElementById("auto-pick-accounts");
    if (autoPickButton) {
      autoPickButton.addEventListener("click", () => {
        const ids = new Set(recommendedAccounts(latestAccountsOverview?.accounts || []).map((account) => Number(account.id)));
        Array.from(accountSelect?.options || []).forEach((option) => {
          option.selected = ids.has(Number(option.value));
        });
        renderAccountSummary(latestAccountsOverview?.accounts || []);
        showFlash(`Автопідбір обрав акаунтів: ${ids.size}.`);
      });
    }

    if (accountRecommendations) {
      accountRecommendations.addEventListener("click", (event) => {
        const card = event.target.closest(".recommendation-card");
        if (!card || !accountSelect) return;
        const option = Array.from(accountSelect.options).find((item) => Number(item.value) === Number(card.dataset.accountId));
        if (option) option.selected = !option.selected;
        renderAccountSummary(latestAccountsOverview?.accounts || []);
      });
    }

    document.querySelectorAll(".parser-source-button").forEach((button) => {
      button.addEventListener("click", () => {
        const input = document.getElementById("bulk-targets-input");
        if (!input) return;
        input.placeholder = button.dataset.source === "groups"
          ? "@group_one\n@group_two\nhttps://t.me/joinchat/..."
          : "@channel_one\n@channel_two\nhttps://t.me/channel";
        input.focus();
        showFlash(button.dataset.source === "groups" ? "Встав сюди експорт груп із парсера." : "Встав сюди експорт каналів із парсера.");
      });
    });

    document.querySelectorAll(".log-filter").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".log-filter").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
        activeLogFilter = button.dataset.filter || "all";
        renderConsole(latestLogs);
      });
    });

    if (logSearch) {
      logSearch.addEventListener("input", () => renderConsole(latestLogs));
    }
  }

  bindForms();
  bindControls();
  refreshWarmup().catch((error) => {
    showFlash(error.message, "danger");
  });
})();
