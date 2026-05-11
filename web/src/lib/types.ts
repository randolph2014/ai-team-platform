export type RunStatus = 'queued' | 'running' | 'paused' | 'resuming' | 'completed' | 'failed' | 'cancelled' | 'archived' | 'blocked';

export interface AgentRun {
  agent_name: string;
  runtime_id?: string;
  runtime_cli?: string;
  role?: string;
  status: string;
  duration_seconds?: number;
  output_file?: string;
  raw_log_file?: string;
  exit_code?: number;
  error_message?: string;
  model_requested?: string;
  model_used?: string;
  started_at?: string;
  completed_at?: string;
}

export interface GateRun {
  name: string;
  type: string;
  status: string;
  command?: string;
  output?: string;
  required: boolean;
  exit_code?: number;
  retry_count?: number;
  started_at?: string;
  completed_at?: string;
}

export type HumanDecisionValue = 'waiting' | 'approved' | 'rejected';

export interface HumanDecision {
  stage_id: string;
  decision: HumanDecisionValue;
  reason: string;
  required_changes: string[];
  target_stage?: string | null;
  decided_by?: string;
  decided_at?: string;
}

export interface ArtifactValidationRun {
  artifact: string;
  status: 'passed' | 'failed' | string;
  message?: string;
  validator?: string;
}

export interface StageRun {
  stage_id: string;
  stage_name: string;
  iteration?: number;
  status: string;
  is_parallel: boolean;
  type: string;
  duration_seconds?: number;
  output_dir?: string;
  error_message?: string;
  started_at?: string;
  completed_at?: string;
  agents: AgentRun[];
  quality_gates: GateRun[];
  artifact_validations?: ArtifactValidationRun[];
  human_decision?: HumanDecision | null;
  loopback_to?: string | null;
}

export interface StatusTimelineEntry {
  status: string;
  timestamp: string;
  reason?: string;
}

export interface StructuredError {
  error_type?: string;
  error_message?: string;
  traceback?: string;
}

export interface RunReport {
  run_id: string;
  status: RunStatus;
  mode?: string;
  requirement: string;
  project_root: string;
  output_dir: string;
  config_source: string;
  config_path?: string;
  started_at?: string;
  completed_at?: string;
  duration_seconds?: number;
  worktree_path?: string;
  merge_result?: Record<string, unknown> | null;
  changed_files?: string[];
  diff_stat?: string;
  stages: StageRun[];
  human_decisions?: HumanDecision[];
  artifacts: string[];
  current_contract_status?: 'passed' | 'failed' | 'unknown' | string;
  current_contract_validations?: ArtifactValidationRun[];
  warnings?: string[];
  error_message?: string;
  error_detail?: StructuredError;
  status_timeline?: StatusTimelineEntry[];
}

export interface RunEvent {
  type: string;
  run_id: string;
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface RunListItem {
  run_id: string;
  status: RunStatus;
  pipeline?: string | null;
  requirement?: string;
  project_root?: string;
  output_dir?: string;
  started_at?: string;
  completed_at?: string;
  duration_seconds?: number;
}

export interface RunListResponse {
  items: RunListItem[];
  total: number;
  page: number;
  size: number;
}

export interface Pipeline {
  id: string;
  name: string;
  description: string;
  yaml_config: Record<string, unknown>;
  stage_count?: number;
  created_at?: string;
  updated_at?: string;
}

export interface RuntimeConfig {
  id?: string;
  name?: string;
  cli: string;
  args?: string[];
  prompt_mode?: 'arg' | 'stdin';
  model_arg_style?: 'long' | 'codex' | string;
  model?: string;
  default_model?: string;
  /** @deprecated fallback_models 已废弃，保留字段仅为向后兼容 */
  fallback_models?: string[];
  env?: Record<string, string>;
  provider?: string;
  available?: boolean;
  configured?: boolean;
  supported?: boolean;
  path?: string | null;
  version?: string | null;
  launch_header?: string;
  unsupported_reason?: string;
  source?: string;
}

export interface AgentConfig {
  name: string;
  runtime_id: string;
  role?: string;
  prompt?: string;
  timeout?: number;
}

export interface AppConfig {
  runtimes?: Record<string, RuntimeConfig>;
  agents?: AgentConfig[];
  [section: string]: unknown;
}

export interface SettingsResponse {
  source: string;
  path: string | null;
  warnings: string[];
  config: AppConfig;
}

export interface RuntimeCandidate extends RuntimeConfig {
  id: string;
  provider: string;
  cli: string;
  available: boolean;
  supported: boolean;
}

export interface RuntimeCatalogResponse {
  runtimes: Record<string, RuntimeConfig>;
  candidates: RuntimeCandidate[];
}

export interface AgentPromptResponse {
  agent_name: string;
  path: string;
  source_path?: string;
  content: string;
}

export interface PipelineTemplate {
  id: string;
  name: string;
  description: string;
  category?: string;
  source?: string;
  is_builtin?: boolean;
  tags?: string[];
  recommended?: boolean;
  estimated_effort?: string;
  stage_count?: number;
  agent_count?: number;
  human_gate_count?: number;
  quality_gate_count?: number;
  stage_summary?: string[];
  stages: string[];
  yaml_config?: Record<string, unknown>;
}

export interface Webhook {
  id: string;
  url: string;
  secret: string;
  events: string[];
  pipeline_id?: string | null;
  enabled: boolean;
  created_at?: string;
}

export type HarnessFileKind = 'config' | 'rule' | 'skill' | 'check' | 'baseline' | 'task' | 'unknown';

export interface HarnessFile {
  path: string;
  hash?: string;
  content: string;
  kind?: HarnessFileKind;
}

export interface HarnessPermission {
  can_view?: boolean;
  can_edit?: boolean;
  can_run_checks?: boolean;
}

export interface HarnessSummary {
  schema_version?: string;
  manifest_hash?: string;
  rules_count?: number;
  skills_count?: number;
  checks_count?: number;
  baselines_count?: number;
  files_count?: number;
  warnings?: string[];
  skills_policy?: string;
  [key: string]: unknown;
}

export interface HarnessValidationResult {
  valid: boolean;
  errors: string[];
  warnings?: string[];
  manifest_hash?: string;
  summary?: HarnessSummary;
}

export interface HarnessBundle {
  project_id: string;
  manifest_hash: string;
  files: HarnessFile[];
  summary?: HarnessSummary;
  validation?: HarnessValidationResult;
  permissions?: HarnessPermission;
}

export interface HarnessConflictPayload {
  error: 'manifest_conflict';
  current_manifest_hash: string;
  changed_files: string[];
}

export interface TaskBoardTask {
  id: string;
  title: string;
  state: string;
  run_id?: string;
  artifact_dir?: string;
  decision_ids?: string[];
  run_ids?: string[];
  artifact_dirs?: string[];
  tags?: string[];
  related_files?: string[];
  decisions?: Array<Record<string, unknown>>;
  risks?: Array<Record<string, unknown>>;
  requirement?: string;
  summary?: string;
  state_history?: Array<Record<string, unknown>>;
  created_at?: string;
  updated_at?: string;
  accepted_at?: string | null;
}

export interface RelatedTask {
  task_id: string;
  title: string;
  state: string;
  summary?: string;
  requirement?: string;
  tags?: string[];
  related_files?: string[];
  run_ids?: string[];
  artifact_dirs?: string[];
  decision_ids?: string[];
  decisions?: Array<Record<string, unknown>>;
  risks?: Array<Record<string, unknown>>;
  updated_at?: string;
  match_score?: number;
  match_reasons?: string[];
}

export interface TaskBoardResponse {
  project_id: string;
  summary: {
    total: number;
    by_state?: Record<string, number>;
  };
  tasks: TaskBoardTask[];
  related_tasks?: RelatedTask[];
}

export interface TaskBoardEventRequest {
  task_id: string;
  title?: string;
  state: string;
  source_stage: string;
  run_id: string;
  artifact_dir: string;
  decision_ids: string[];
  event_type?: string;
  decision?: string;
  requirement?: string;
  summary?: string;
  tags?: string[];
  related_files?: string[];
  decisions?: Array<Record<string, unknown>>;
  risks?: Array<Record<string, unknown>>;
  message?: string;
}

export interface HarnessReportCheck {
  id: string;
  type: 'pattern' | 'command' | 'baseline' | 'unknown' | string;
  status: 'pass' | 'warning' | 'fail' | 'skipped' | string;
  severity: 'info' | 'warning' | 'error' | string;
  blocking: boolean;
  duration_ms: number;
  exit_code: number | null;
  matched_files: string[];
  output_excerpt: string;
  evidence_refs: string[];
}

export interface HarnessReport {
  schema_version: string;
  run_id: string;
  project_id: string;
  stage_id: string;
  harness_config_hash: string;
  generated_at: string;
  status: 'pass' | 'warning' | 'fail' | string;
  blocking: boolean;
  summary: {
    total: number;
    passed: number;
    warnings: number;
    failed: number;
    skipped: number;
  };
  checks: HarnessReportCheck[];
  baseline_results: Array<Record<string, unknown>>;
  rule_violations: Array<Record<string, unknown>>;
  warnings: string[];
  evidence: string[];
  next_stage_contract: Record<string, unknown>;
}
