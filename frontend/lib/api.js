"use client";

export function getCookie(name) {
  if (typeof document === "undefined") return "";
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : "";
}

const apiBaseUrl = (process.env.NEXT_PUBLIC_BACKEND_URL || "").replace(/\/$/, "");

function isFormData(value) {
  return typeof FormData !== "undefined" && value instanceof FormData;
}

export function authTokens() {
  if (typeof window === "undefined") return { access: "", refresh: "" };
  return {
    access: window.localStorage.getItem("stogramgpt_access") || "",
    refresh: window.localStorage.getItem("stogramgpt_refresh") || "",
  };
}

export function saveAuthTokens(tokens = {}) {
  if (typeof window === "undefined") return;
  if (tokens.access) window.localStorage.setItem("stogramgpt_access", tokens.access);
  if (tokens.refresh) window.localStorage.setItem("stogramgpt_refresh", tokens.refresh);
}

export function clearAuthTokens() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem("stogramgpt_access");
  window.localStorage.removeItem("stogramgpt_refresh");
}

export function persistTokensFromUrl() {
  if (typeof window === "undefined" || !window.location.hash) return false;
  const params = new URLSearchParams(window.location.hash.slice(1));
  const access = params.get("access");
  const refresh = params.get("refresh");
  if (!access || !refresh) return false;
  saveAuthTokens({ access, refresh });
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  return true;
}

function apiUrl(path) {
  if (path.startsWith("http")) return path;
  if (path.startsWith("/api/") && apiBaseUrl) return `${apiBaseUrl}${path}`;
  return path;
}

export function backendApiUrl(path) {
  return apiUrl(path);
}

async function refreshAccessToken() {
  const { refresh } = authTokens();
  if (!refresh) return "";
  const response = await fetch(apiUrl("/api/v1/auth/token/refresh/"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
  if (!response.ok) {
    clearAuthTokens();
    return "";
  }
  const payload = await response.json();
  saveAuthTokens({ access: payload.access, refresh: payload.refresh || refresh });
  return payload.access || "";
}

export async function apiFetch(path, options = {}) {
  const method = options.method || "GET";
  const headers = new Headers(options.headers || {});
  const body = options.body;
  const { access } = authTokens();

  if (body && !isFormData(body) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (access && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${access}`);
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase())) {
    const csrf = getCookie("csrftoken");
    if (csrf) headers.set("X-CSRFToken", csrf);
  }

  let response;
  try {
    response = await fetch(apiUrl(path), {
      ...options,
      method,
      headers,
      credentials: "include",
      body: body && !isFormData(body) && typeof body !== "string" ? JSON.stringify(body) : body,
    });
  } catch (error) {
    throw new Error(
      `Network request failed: ${path}. ${error instanceof Error ? error.message : String(error)}`,
    );
  }

  if (response.status === 401 && !options.__retried) {
    const nextAccess = await refreshAccessToken();
    if (nextAccess) {
      return apiFetch(path, { ...options, __retried: true });
    }
  }

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      throw new Error("AUTH_REQUIRED");
    }
    const detail = typeof payload === "string" ? payload : payload.detail || JSON.stringify(payload);
    throw new Error(detail || `HTTP ${response.status}`);
  }

  return payload;
}

export function normalizeApiError(error) {
  const message = error instanceof Error ? error.message : String(error);
  if (message.includes("<!DOCTYPE html") || message.includes("<html")) {
    const titleMatch = message.match(/<title>(.*?)<\/title>/i);
    const title = titleMatch ? titleMatch[1].replace(/\s+/g, " ").trim() : "";
    return title || "Backend повернув HTML error page. Перевір логи Django.";
  }
  try {
    const parsed = JSON.parse(message);
    if (typeof parsed === "object" && parsed !== null) {
      return Object.entries(parsed)
        .map(([field, value]) => `${field}: ${Array.isArray(value) ? value.join(", ") : value}`)
        .join("; ");
    }
  } catch {
    // Keep original message.
  }
  return message;
}

export function mediaUrl(path) {
  if (!path) return "";
  return path.startsWith("http") ? path : path;
}
