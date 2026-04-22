const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || process.env.BACKEND_URL || "http://127.0.0.1:8000";

const hopByHopHeaders = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function backendHostHeader() {
  try {
    return new URL(backendUrl).host;
  } catch {
    return "127.0.0.1:8000";
  }
}

function backendPath(request, prefix, parts) {
  const suffix = parts?.length ? `/${parts.join("/")}` : "";
  return `${backendUrl}/${prefix}${suffix}/${request.nextUrl.search}`;
}

export async function proxyToBackend(request, prefix, parts) {
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!hopByHopHeaders.has(key.toLowerCase())) headers.set(key, value);
  });
  headers.set("host", backendHostHeader());
  headers.set("x-forwarded-host", request.headers.get("host") || "");
  headers.set("x-forwarded-proto", request.nextUrl.protocol.replace(":", ""));

  const method = request.method.toUpperCase();
  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();
  let response;
  const target = backendPath(request, prefix, parts);
  try {
    response = await fetch(target, {
      method,
      headers,
      body,
      redirect: "manual",
    });
  } catch (error) {
    return Response.json(
      {
        detail: "Django backend is unavailable for Next proxy.",
        backend_url: backendUrl,
        target,
        error: error instanceof Error ? error.message : String(error),
      },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  response.headers.forEach((value, key) => {
    if (!hopByHopHeaders.has(key.toLowerCase())) responseHeaders.set(key, value);
  });

  if (typeof response.headers.getSetCookie === "function") {
    responseHeaders.delete("set-cookie");
    for (const cookie of response.headers.getSetCookie()) {
      responseHeaders.append("set-cookie", cookie);
    }
  }

  const location = responseHeaders.get("location");
  if (location?.startsWith(backendUrl)) {
    responseHeaders.set("location", location.replace(backendUrl, ""));
  }

  const responseBody = method === "HEAD" ? null : await response.arrayBuffer();
  return new Response(responseBody, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders,
  });
}
