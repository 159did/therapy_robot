export class ApiError extends Error {
  constructor(path, status, payload = {}) {
    const safePayload = payload && typeof payload === 'object' ? payload : {};
    const message = safePayload.error || safePayload.message || `${path} HTTP ${status}`;
    super(message);
    this.name = 'ApiError';
    this.path = path;
    this.status = status;
    this.payload = safePayload;
    this.errorCode = safePayload.error_code || '';
    this.executionLocked = safePayload.execution_locked === true;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    throw new ApiError(path, 0, { error: error?.message || 'network unavailable' });
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(path, response.status, payload);
  return payload;
}

export const api = {
  async getState() {
    return request('/api/state');
  },
  async getWorkflowState() {
    return request('/api/workflow/state', {
      method: 'GET',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
  },
  async getWorkflowSelfCheck() {
    return request('/api/workflow/self_check', {
      method: 'GET',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
  },
  async getMotionPlanPreview(side) {
    if (side !== 'left' && side !== 'right') {
      throw new ApiError('/api/motion_plan/preview', 0, {
        error: 'invalid motion plan side',
        error_code: 'invalid_motion_plan_side',
      });
    }
    return request(`/api/motion_plan/preview?side=${side}`, {
      method: 'GET',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
  },
  async get(path) {
    return request(path);
  },
  async post(path, body = {}) {
    return request(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  },
};
