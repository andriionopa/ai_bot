(function () {
  const config = window.profilePageConfig || {};
  const csrfToken = (() => {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  })();

  const flashBox = document.getElementById("flash-box");
  const accountSelect = document.getElementById("profile-account-select");
  const draftForm = document.getElementById("profile-draft-form");
  const profilesTbody = document.getElementById("profiles-tbody");

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function showFlash(message, tone = "info") {
    if (!flashBox) {
      return;
    }
    flashBox.hidden = false;
    flashBox.className = `flash-box flash-${tone}`;
    flashBox.textContent = message;
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

  async function loadAccounts() {
    const data = await apiFetch(config.overviewUrl, {method: "GET"});
    const accounts = (data.accounts || []).filter((account) => account.auth_state === "connected");
    if (!accountSelect) {
      return;
    }
    if (!accounts.length) {
      accountSelect.innerHTML = '<option value="">Немає connected акаунтів</option>';
      return;
    }
    accountSelect.innerHTML = accounts
      .map((account) => `<option value="${account.id}">${escapeHtml(account.label)} · ${escapeHtml(account.phone_number || account.session_name)}</option>`)
      .join("");
  }

  function photoPreview(draft) {
    if (!draft.photo) {
      return '<span class="meta">Фото ще немає</span>';
    }
    return `<a class="button button-ghost" href="${escapeHtml(draft.photo)}" target="_blank" rel="noreferrer">Відкрити</a>`;
  }

  function renderDrafts(drafts) {
    if (!profilesTbody) {
      return;
    }
    if (!drafts.length) {
      profilesTbody.innerHTML = '<tr><td colspan="5" class="empty-state">Чернеток поки немає.</td></tr>';
      return;
    }
    profilesTbody.innerHTML = drafts.map((draft) => `
      <tr>
        <td>
          <strong>${escapeHtml(draft.account_label)}</strong>
          <div class="meta">#${escapeHtml(draft.account)}</div>
        </td>
        <td>
          <span class="pill pill-inline">${escapeHtml(draft.gender)}</span>
          <div class="meta">${escapeHtml(draft.birth_date || "без дати")} · ${escapeHtml(draft.country)}</div>
          <div class="meta">${escapeHtml(draft.profession)}</div>
          <div class="meta">${escapeHtml(draft.telegram_channel)}</div>
        </td>
        <td>
          <div class="meta">Telegram → Profile → Bio</div>
          <div>${escapeHtml(draft.bio || "Біо ще немає")}</div>
          <div class="profile-inline-form">
            <input class="input profile-bio-input" data-bio-input="${draft.id}" maxlength="70" value="${escapeHtml(draft.bio || "")}" placeholder="ручне біо" />
            <button class="button button-ghost profile-action" type="button" data-action="save-bio" data-id="${draft.id}">Зберегти біо</button>
          </div>
        </td>
        <td>
          ${photoPreview(draft)}
          <form class="profile-upload-form" data-upload-id="${draft.id}" enctype="multipart/form-data">
            <input class="input input-file" type="file" name="photo" accept="image/*" required />
            <button class="button button-ghost" type="submit">Upload</button>
          </form>
        </td>
        <td>
          <span class="state-chip state-${escapeHtml(draft.status)}">${escapeHtml(draft.status)}</span>
          ${draft.last_error ? `<div class="meta meta-danger">${escapeHtml(draft.last_error)}</div>` : ""}
          <div class="profile-actions">
            <button class="button button-ghost profile-action" type="button" data-action="generate-bio" data-id="${draft.id}">AI біо</button>
            <button class="button button-ghost profile-action" type="button" data-action="generate-photo" data-id="${draft.id}">AI фото</button>
            <button class="button button-primary profile-action" type="button" data-action="apply" data-id="${draft.id}">Застосувати</button>
            <button class="button button-danger profile-action" type="button" data-action="delete" data-id="${draft.id}">Видалити</button>
          </div>
        </td>
      </tr>
    `).join("");
  }

  async function loadDrafts() {
    const drafts = await apiFetch(config.profileDraftsUrl, {method: "GET"});
    renderDrafts(drafts);
  }

  async function createDraft() {
    const formData = new FormData(draftForm);
    await apiFetch(config.profileDraftsUrl, {method: "POST", body: formData});
    draftForm.reset();
    showFlash("Чернетку профілю створено.");
    await loadDrafts();
  }

  async function postDraftAction(id, action) {
    if (action === "delete") {
      if (!window.confirm("Видалити цю чернетку профілю?")) {
        return;
      }
      await apiFetch(`${config.profileDraftsUrl}${id}/`, {method: "DELETE"});
      showFlash(`Чернетку #${id} видалено.`, "warning");
      await loadDrafts();
      return;
    }
    if (action === "save-bio") {
      const input = document.querySelector(`[data-bio-input="${id}"]`);
      const payload = await apiFetch(`${config.profileDraftsUrl}${id}/`, {
        method: "PATCH",
        body: JSON.stringify({bio: input?.value || ""}),
      });
      showFlash(`Чернетка #${payload.id}: біо збережено.`);
      await loadDrafts();
      return;
    }
    const payload = await apiFetch(`${config.profileDraftsUrl}${id}/${action}/`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (payload.status === "failed") {
      showFlash(payload.last_error || "Дія завершилась помилкою.", "danger");
    } else {
      showFlash(`Чернетка #${payload.id}: ${payload.status}.`);
    }
    await loadDrafts();
  }

  async function uploadPhoto(form) {
    const id = form.dataset.uploadId;
    const formData = new FormData(form);
    await apiFetch(`${config.profileDraftsUrl}${id}/upload-photo/`, {method: "POST", body: formData});
    showFlash("Фото завантажено в чернетку.");
    await loadDrafts();
  }

  function bindEvents() {
    if (draftForm) {
      draftForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          await createDraft();
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }

    const refresh = document.getElementById("refresh-profiles");
    if (refresh) {
      refresh.addEventListener("click", async () => {
        try {
          await loadAccounts();
          await loadDrafts();
          showFlash("Профілі оновлено.");
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }

    if (profilesTbody) {
      profilesTbody.addEventListener("click", async (event) => {
        const button = event.target.closest(".profile-action");
        if (!button) {
          return;
        }
        try {
          await postDraftAction(button.dataset.id, button.dataset.action);
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });

      profilesTbody.addEventListener("submit", async (event) => {
        const form = event.target.closest(".profile-upload-form");
        if (!form) {
          return;
        }
        event.preventDefault();
        try {
          await uploadPhoto(form);
        } catch (error) {
          showFlash(error.message, "danger");
        }
      });
    }
  }

  bindEvents();
  Promise.all([loadAccounts(), loadDrafts()]).catch((error) => {
    showFlash(error.message, "danger");
  });
})();
