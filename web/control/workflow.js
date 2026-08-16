import { api } from './api.js';

const WORKFLOW_STATES = new Set([
  'offline',
  'fault',
  'locked',
  'storage',
  'standby',
  'vision_blocked',
  'ready_for_preview',
  'preview_blocked',
]);
const READ_ONLY_ACTIONS = new Set([
  'view_state',
  'view_self_check',
  'refresh_state',
  'preview_motion_plan',
]);
const REASON_SEVERITIES = new Set(['info', 'warning', 'blocking']);
const CHECK_STATUSES = new Set(['pass', 'fail', 'unknown']);
const SUMMARY_STATUSES = new Set(['pass', 'blocked']);
const PLAN_PHASES = new Set([
  'lift',
  'side_transit',
  'preview_approach',
  'preview_retract',
  'return_transit',
  'lower',
]);
const JOINT_KEYS = ['k0_m', 'k1_rad', 'k2_rad', 'k3_rad', 'k4_rad'];

export class WorkflowContractError extends Error {
  constructor(path, field, detail) {
    super(`${path}: ${field} ${detail}`);
    this.name = 'WorkflowContractError';
    this.path = path;
    this.field = field;
    this.errorCode = 'invalid_workflow_contract';
    this.executionLocked = true;
  }
}

function contractError(path, field, detail) {
  throw new WorkflowContractError(path, field, detail);
}

function requireObject(value, path, field) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    contractError(path, field, 'must be an object');
  }
  return value;
}

function requireString(value, path, field, allowEmpty = false) {
  if (typeof value !== 'string' || (!allowEmpty && value.length === 0)) {
    contractError(path, field, 'must be a string');
  }
  return value;
}

function requireBoolean(value, expected, path, field) {
  if (value !== expected) {
    contractError(path, field, `must be ${expected}`);
  }
}

function requireInteger(value, path, field) {
  if (!Number.isSafeInteger(value) || value < 0) {
    contractError(path, field, 'must be a non-negative safe integer');
  }
}

function requireFiniteNumber(value, path, field) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    contractError(path, field, 'must be a finite number');
  }
}

function validateSummary(summary, path, field = 'self_check_summary') {
  requireObject(summary, path, field);
  if (!SUMMARY_STATUSES.has(summary.status)) {
    contractError(path, `${field}.status`, 'is unknown');
  }
  for (const key of ['passed', 'failed', 'unknown']) {
    requireInteger(summary[key], path, `${field}.${key}`);
  }
}

function validateBlockingReasons(reasons, path) {
  if (!Array.isArray(reasons)) {
    contractError(path, 'blocking_reasons', 'must be an array');
  }
  reasons.forEach((reason, index) => {
    const field = `blocking_reasons[${index}]`;
    requireObject(reason, path, field);
    requireString(reason.code, path, `${field}.code`);
    requireString(reason.source, path, `${field}.source`);
    requireString(reason.message, path, `${field}.message`, true);
    if (!REASON_SEVERITIES.has(reason.severity)) {
      contractError(path, `${field}.severity`, 'is unknown');
    }
  });
}

function validateCommon(payload, path) {
  requireObject(payload, path, 'response');
  if (payload.schema_version !== 'b2.v1') {
    contractError(path, 'schema_version', 'must be b2.v1');
  }
  requireBoolean(payload.ok, true, path, 'ok');
  requireBoolean(payload.motor_command_written, false, path, 'motor_command_written');
  const source = requireObject(payload.source_state, path, 'source_state');
  for (const key of ['command_seq', 'target_command_seq', 'endpoint_target_seq']) {
    requireInteger(source[key], path, `source_state.${key}`);
  }
  validateBlockingReasons(payload.blocking_reasons, path);
  return payload;
}

function validateNullablePlanIdentity(value, pattern, path, field) {
  if (value === null) return;
  if (typeof value !== 'string' || !pattern.test(value)) {
    contractError(path, field, 'has an invalid format');
  }
}

export function validateWorkflowState(payload) {
  const path = '/api/workflow/state';
  validateCommon(payload, path);
  if (!WORKFLOW_STATES.has(payload.workflow_state)) {
    contractError(path, 'workflow_state', 'is unknown');
  }
  if (!Array.isArray(payload.allowed_actions)) {
    contractError(path, 'allowed_actions', 'must be an array');
  }
  payload.allowed_actions.forEach((action, index) => {
    if (!READ_ONLY_ACTIONS.has(action)) {
      contractError(path, `allowed_actions[${index}]`, 'is not a read-only action');
    }
  });
  validateSummary(payload.self_check_summary, path);
  validateNullablePlanIdentity(payload.plan_id, /^b2-[0-9a-f]{16}$/, path, 'plan_id');
  validateNullablePlanIdentity(payload.plan_hash, /^sha256:[0-9a-f]{64}$/, path, 'plan_hash');
  if ((payload.plan_id === null) !== (payload.plan_hash === null)) {
    contractError(path, 'plan_id/plan_hash', 'must both be null or both be present');
  }
  requireBoolean(payload.execution_locked, true, path, 'execution_locked');
  return payload;
}

export function validateWorkflowSelfCheck(payload) {
  const path = '/api/workflow/self_check';
  validateCommon(payload, path);
  validateSummary(payload.self_check_summary, path);
  if (!Array.isArray(payload.checks)) {
    contractError(path, 'checks', 'must be an array');
  }
  payload.checks.forEach((check, index) => {
    const field = `checks[${index}]`;
    requireObject(check, path, field);
    requireString(check.id, path, `${field}.id`);
    if (!CHECK_STATUSES.has(check.status)) {
      contractError(path, `${field}.status`, 'is unknown');
    }
    if (typeof check.blocking !== 'boolean') {
      contractError(path, `${field}.blocking`, 'must be a boolean');
    }
    if (check.reason_code !== null) {
      requireString(check.reason_code, path, `${field}.reason_code`);
    }
    requireString(check.observed, path, `${field}.observed`, true);
  });
  const summary = payload.self_check_summary;
  if (summary.passed + summary.failed + summary.unknown !== payload.checks.length) {
    contractError(path, 'self_check_summary', 'does not match checks');
  }
  return payload;
}

function validateJoints(waypoint, path, field) {
  requireObject(waypoint, path, field);
  const joints = requireObject(waypoint.joints, path, `${field}.joints`);
  for (const key of JOINT_KEYS) {
    requireFiniteNumber(joints[key], path, `${field}.joints.${key}`);
  }
}

function validatePlanSegment(segment, index, path) {
  const field = `plan.segments[${index}]`;
  requireObject(segment, path, field);
  requireString(segment.segment_id, path, `${field}.segment_id`);
  if (!PLAN_PHASES.has(segment.phase)) {
    contractError(path, `${field}.phase`, 'is unknown');
  }
  validateJoints(segment.start, path, `${field}.start`);
  validateJoints(segment.target, path, `${field}.target`);
  const preflight = requireObject(segment.preflight, path, `${field}.preflight`);
  if (typeof preflight.ok !== 'boolean') {
    contractError(path, `${field}.preflight.ok`, 'must be a boolean');
  }
  if (typeof preflight.collision_checked !== 'boolean') {
    contractError(path, `${field}.preflight.collision_checked`, 'must be a boolean');
  }
  requireString(preflight.reason_code, path, `${field}.preflight.reason_code`);
  requireString(preflight.collision_link, path, `${field}.preflight.collision_link`, true);
  requireString(preflight.collision_obstacle, path, `${field}.preflight.collision_obstacle`, true);
  requireFiniteNumber(preflight.path_fraction, path, `${field}.preflight.path_fraction`);
  if (preflight.path_fraction < 0 || preflight.path_fraction > 1) {
    contractError(path, `${field}.preflight.path_fraction`, 'must be between 0 and 1');
  }
}

export function validateMotionPlanPreview(payload, expectedSide) {
  const path = `/api/motion_plan/preview?side=${expectedSide}`;
  if (expectedSide !== 'left' && expectedSide !== 'right') {
    contractError(path, 'side', 'must be left or right');
  }
  validateCommon(payload, path);
  validateNullablePlanIdentity(payload.plan_id, /^b2-[0-9a-f]{16}$/, path, 'plan_id');
  validateNullablePlanIdentity(payload.plan_hash, /^sha256:[0-9a-f]{64}$/, path, 'plan_hash');
  if (payload.plan_id === null || payload.plan_hash === null) {
    contractError(path, 'plan_id/plan_hash', 'must be present');
  }
  if (typeof payload.preview_valid !== 'boolean') {
    contractError(path, 'preview_valid', 'must be a boolean');
  }
  requireBoolean(payload.execution_allowed, false, path, 'execution_allowed');
  const plan = requireObject(payload.plan, path, 'plan');
  if (plan.schema_version !== 'b2.motion-plan.v1') {
    contractError(path, 'plan.schema_version', 'must be b2.motion-plan.v1');
  }
  if (plan.side !== expectedSide) {
    contractError(path, 'plan.side', 'does not match the requested side');
  }
  if (plan.coordinate_frame !== 'robot_base') {
    contractError(path, 'plan.coordinate_frame', 'must be robot_base');
  }
  const units = requireObject(plan.units, path, 'plan.units');
  if (units.linear !== 'm' || units.angular !== 'rad') {
    contractError(path, 'plan.units', 'must use m and rad');
  }
  requireBoolean(plan.formal_use_allowed, false, path, 'plan.formal_use_allowed');
  if (!Array.isArray(plan.segments)) {
    contractError(path, 'plan.segments', 'must be an array');
  }
  plan.segments.forEach((segment, index) => validatePlanSegment(segment, index, path));
  return payload;
}

export function createWorkflowClient(apiClient = api) {
  return Object.freeze({
    async getState() {
      return validateWorkflowState(await apiClient.getWorkflowState());
    },
    async getSelfCheck() {
      return validateWorkflowSelfCheck(await apiClient.getWorkflowSelfCheck());
    },
    async getMotionPlan(side) {
      return validateMotionPlanPreview(await apiClient.getMotionPlanPreview(side), side);
    },
  });
}

export const workflowClient = createWorkflowClient();
