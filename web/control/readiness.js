const READINESS_PATH = '/api/readiness/attestation';

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function requiredString(value, label) {
  if (typeof value !== 'string' || value.length === 0) throw new Error(`${label} missing`);
  return value;
}

function requiredBoolean(value, label, expected) {
  if (typeof value !== 'boolean' || (expected !== undefined && value !== expected)) {
    throw new Error(`${label} invalid`);
  }
  return value;
}

function validateAttestation(value, now = Date.now()) {
  if (!isObject(value) || value.schema_version !== 'b3.v1') throw new Error('unknown readiness schema');
  for (const key of ['motor_command_written', 'execution_allowed', 'entity_action_authorized', 'nano_deployment_authorized']) {
    requiredBoolean(value[key], key, false);
  }
  requiredBoolean(value.ok, 'ok');
  if (value.authorization_scope !== 'software_precheck_only') throw new Error('authorization scope invalid');
  requiredString(value.attestation_id, 'attestation_id');
  requiredString(value.source_fingerprint, 'source_fingerprint');
  requiredString(value.software_commit, 'software_commit');
  for (const key of ['issued_at_ms', 'expires_at_ms']) {
    if (!Number.isSafeInteger(value[key])) throw new Error(`${key} invalid`);
  }
  if (value.expires_at_ms < value.issued_at_ms || value.expires_at_ms - value.issued_at_ms > 300000) {
    throw new Error('readiness validity invalid');
  }
  if (value.issued_at_ms > now || now > value.expires_at_ms) throw new Error('readiness expired or clock is before issue');
  if (!isObject(value.source_state)) throw new Error('source_state missing');
  for (const key of ['command_seq', 'target_command_seq', 'endpoint_target_seq']) {
    if (!Number.isSafeInteger(value.source_state[key])) throw new Error(`source_state.${key} invalid`);
  }
  if (!isObject(value.config_hashes) && !Array.isArray(value.config_hashes)) throw new Error('config_hashes missing');
  if (!Array.isArray(value.checks) || !Array.isArray(value.blocking_reasons)) throw new Error('readiness lists missing');
  return Object.freeze(value);
}

export async function getReadinessAttestation(fetchImpl = fetch, clock = () => Date.now()) {
  let response;
  try {
    response = await fetchImpl(READINESS_PATH, {
      method: 'GET',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
  } catch (error) {
    throw new Error(`readiness network failure: ${error?.message || 'unavailable'}`);
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(`readiness HTTP ${response.status}`);
  const now = typeof clock === 'function' ? clock() : clock;
  return validateAttestation(payload, now);
}

export { READINESS_PATH, validateAttestation };
