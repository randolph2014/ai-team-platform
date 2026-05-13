import type { PipelineTemplate } from './types';

type StageRecord = {
  id?: unknown;
  name?: unknown;
  type?: unknown;
  agents?: unknown;
};

function stageRecords(template: PipelineTemplate): StageRecord[] {
  const configStages = template.yaml_config?.stages;
  if (Array.isArray(configStages)) {
    return configStages.filter((stage): stage is StageRecord => Boolean(stage) && typeof stage === 'object');
  }
  const labels = template.stage_summary && template.stage_summary.length > 0 ? template.stage_summary : template.stages;
  return labels.map((label) => ({ id: label, name: label }));
}

function agentRuntimeMap(template: PipelineTemplate): Record<string, string> {
  const configAgents = template.yaml_config?.agents;
  if (!Array.isArray(configAgents)) return {};
  const map: Record<string, string> = {};
  for (const item of configAgents) {
    if (!item || typeof item !== 'object') continue;
    const record = item as Record<string, unknown>;
    if (typeof record.name === 'string' && typeof record.runtime_id === 'string') {
      map[record.name] = record.runtime_id;
    }
  }
  return map;
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map(String).filter(Boolean);
}

function stageRuntimeLabel(stage: StageRecord, runtimes: Record<string, string>): string {
  const agents = stringArray(stage.agents);
  if (agents.length > 0) {
    return agents.map((agent) => (runtimes[agent] ? `${agent}/${runtimes[agent]}` : agent)).join('、');
  }
  const id = typeof stage.id === 'string' ? stage.id : '';
  const type = typeof stage.type === 'string' ? stage.type : '';
  if (type === 'human_review' || id.endsWith('_confirm')) return '人工确认';
  return '系统';
}

export function pipelineStageRuntimeSummary(template: PipelineTemplate): string {
  const runtimes = agentRuntimeMap(template);
  return stageRecords(template)
    .map((stage) => {
      const label = typeof stage.name === 'string' && stage.name ? stage.name : String(stage.id || '');
      return `${label}（${stageRuntimeLabel(stage, runtimes)}）`;
    })
    .join(' → ');
}
