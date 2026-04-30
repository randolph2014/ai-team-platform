export type RunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'waiting';

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

export interface RunReport {
  run_id: string;
  status: RunStatus;
  requirement: string;
  project_root: string;
  output_dir: string;
  config_source: string;
  started_at?: string;
  completed_at?: string;
  duration_seconds?: number;
  stages: StageRun[];
  human_decisions?: HumanDecision[];
  artifacts: string[];
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
  output_dir?: string;
  started_at?: string;
  completed_at?: string;
  duration_seconds?: number;
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
