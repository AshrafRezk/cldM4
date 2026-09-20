export function json(status, body, extraHeaders = {}) {
  return {
    statusCode: status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      ...extraHeaders,
    },
    body: JSON.stringify(body),
  };
}

export function httpError(status, message, extra = {}) {
  const err = new Error(message);
  err.statusCode = status;
  err.payload = { error: message, ...extra };
  return err;
}

export function readJson(event) {
  if (!event.body) return {};
  const raw = event.isBase64Encoded
    ? Buffer.from(event.body, "base64").toString("utf8")
    : event.body;
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw httpError(400, "Body must be a JSON object.");
    }
    return parsed;
  } catch (err) {
    if (err.statusCode) throw err;
    throw httpError(400, "Body must be JSON.");
  }
}

export function routePath(event) {
  let path = event.path || "/";
  path = path.replace(/^\/\.netlify\/functions\/api/, "");
  path = path.replace(/^\/api/, "");
  if (!path.startsWith("/")) path = `/${path}`;
  if (path.length > 1 && path.endsWith("/")) path = path.slice(0, -1);
  return path;
}
