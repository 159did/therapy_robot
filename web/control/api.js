export const api = {
  async getState() {
    const response = await fetch('/api/state');
    if (!response.ok) throw new Error(`state HTTP ${response.status}`);
    return response.json();
  },
  async get(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`${path} HTTP ${response.status}`);
    return response.json();
  },
  async post(path, body = {}) {
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `${path} HTTP ${response.status}`);
    return payload;
  },
};
