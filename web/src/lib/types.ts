export type RunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'waiting';

export interface AgentRun {
  agent_name: string;
  provider: string;
  role?: string;
  status: string;
  duration_seconds?: number;
  output_file?: string;
}

export interface GateRun {
  name: string;
  type: string;
  status: string;
  command?: string;
  output?: string;
  required: boolean;
}

export interface StageRun {
  stage_id: string;
  stage_name: string;
  iteration?: number;
  status: string;
  is_parallel: boolean;
  type: string;
  duration_seconds?: number;
  agents: AgentRun[];
  quality_gates: GateRun[];
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
  yaml: string;
  stage_count?: number;
  created_at?: string;
  updated_at?: string;
}

export interface SettingsResponse {
  source: string;
  path: string | null;
  warnings: string[];
  config: Record<string, unknown>;
}

export interface PipelineTemplate {
  id: string;
  name: string;
  description: string;
  stages: string[];
}
