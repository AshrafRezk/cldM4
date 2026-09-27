async function request(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
    ...options,
  });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { error: text || response.statusText };
  }
  if (!response.ok) {
    const err = new Error(data?.error || `Request failed (${response.status})`);
    err.status = response.status;
    err.data = data;
    throw err;
  }
  return data;
}

export const api = {
  me: () => request("/me"),
  scopes: () => request("/scopes"),
  tenants: () => request("/tenants"),
  createTenant: (body) => request("/tenants", { method: "POST", body: JSON.stringify(body) }),
  keys: (tenantId) => request(`/tenants/${tenantId}/keys`),
  mintKey: (tenantId, body) =>
    request(`/tenants/${tenantId}/keys`, { method: "POST", body: JSON.stringify(body) }),
  revokeKey: (keyId) => request(`/keys/${keyId}/revoke`, { method: "POST", body: "{}" }),
  usage: (keyId) => request(`/keys/${keyId}/usage`),
  salesforce: () => request("/salesforce-snippet"),
  openapiUrl: (keyId, target) =>
    target ? `/api/keys/${keyId}/openapi?target=${encodeURIComponent(target)}` : `/api/keys/${keyId}/openapi`,
};
