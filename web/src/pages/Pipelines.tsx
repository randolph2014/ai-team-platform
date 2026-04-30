import { AlertTriangle, Boxes, Edit3, Plus, Trash2, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { createPipeline, deletePipeline, fetchPipelineTemplates, fetchPipelines, updatePipeline } from '../lib/api';
import type { Pipeline, PipelineTemplate } from '../lib/types';

const DEFAULT_YAML = `name: my-pipeline
description: A new pipeline
stages:
  - id: context_scan
    name: 代码库扫描
    type: context_scan
  - id: requirement_synthesis
    name: 需求综合定稿
    agents: [requirements-analyst]
  - id: requirement_confirm
    name: 需求人工确认
    type: human_review
  - id: planning
    name: 方案与任务规划
    agents: [planner]
  - id: task_plan_confirm
    name: 任务规划人工确认
    type: human_review
  - id: develop
    name: 开发实施
    agents: [tech-lead]
  - id: qa
    name: 自动测试
    agents: [qa-automation]
  - id: review
    name: 代码审查与风险识别
    agents: [code-reviewer]
  - id: acceptance_confirm
    name: 最终人工验收
    type: human_review
`;

function cleanScalar(value: string): string {
  const trimmed = value.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function parseInlineList(value: string): string[] {
  const trimmed = value.trim();
  if (!trimmed.startsWith('[') || !trimmed.endsWith(']')) {
    return trimmed ? [cleanScalar(trimmed)] : [];
  }
  return trimmed
    .slice(1, -1)
    .split(',')
    .map((item) => cleanScalar(item))
    .filter(Boolean);
}

const ARRAY_STAGE_FIELDS = new Set(['agents', 'input', 'json_artifacts', 'required_artifacts', 'loopback_trigger']);
const BOOLEAN_STAGE_FIELDS = new Set(['is_parallel', 'parallel', 'allow_auto_approve', 'allow_auto_skip', 'requires_reason_on_reject']);
const NUMBER_STAGE_FIELDS = new Set(['max_retries']);

function parseStageFieldValue(key: string, value: string): unknown {
  const trimmed = value.trim();
  if (ARRAY_STAGE_FIELDS.has(key)) {
    return parseInlineList(trimmed);
  }
  if (BOOLEAN_STAGE_FIELDS.has(key)) {
    return trimmed === 'true';
  }
  if (NUMBER_STAGE_FIELDS.has(key)) {
    const numberValue = Number(trimmed);
    return Number.isFinite(numberValue) ? numberValue : cleanScalar(trimmed);
  }
  return cleanScalar(trimmed);
}

function parsePipelineYaml(text: string): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  const stages: Array<Record<string, unknown>> = [];
  let currentStage: Record<string, unknown> | null = null;
  let nestedKey: string | null = null;

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.replace(/\s+$/, '');
    const topLevel = line.match(/^([a-zA-Z_][\w-]*):\s*(.*)$/);
    if (topLevel && !line.startsWith(' ')) {
      const [, key, value] = topLevel;
      if (key === 'stages') continue;
      config[key] = cleanScalar(value);
      continue;
    }

    const stageStart = line.match(/^\s{2}-\s+id:\s*(.+)$/);
    if (stageStart) {
      currentStage = { id: cleanScalar(stageStart[1]), agents: [] };
      stages.push(currentStage);
      nestedKey = null;
      continue;
    }

    const stageField = line.match(/^\s{4}([a-zA-Z_][\w-]*):\s*(.*)$/);
    if (stageField && currentStage) {
      const [, key, value] = stageField;
      nestedKey = null;
      if (!value.trim()) {
        currentStage[key] = ARRAY_STAGE_FIELDS.has(key) ? [] : {};
        nestedKey = key;
      } else if (key === 'parallel') {
        currentStage.parallel = value.trim() === 'true';
        currentStage.is_parallel = value.trim() === 'true';
      } else {
        currentStage[key] = parseStageFieldValue(key, value);
      }
      continue;
    }

    const nestedListItem = line.match(/^\s{6}-\s+(.+)$/);
    if (nestedListItem && currentStage && nestedKey && Array.isArray(currentStage[nestedKey])) {
      (currentStage[nestedKey] as string[]).push(cleanScalar(nestedListItem[1]));
      continue;
    }

    const nestedField = line.match(/^\s{6}([a-zA-Z_][\w-]*):\s*(.*)$/);
    if (nestedField && currentStage && nestedKey) {
      const nestedValue = currentStage[nestedKey];
      if (nestedValue && typeof nestedValue === 'object' && !Array.isArray(nestedValue)) {
        const [, key, value] = nestedField;
        (nestedValue as Record<string, unknown>)[key] = cleanScalar(value);
      }
    }
  }

  config.stages = stages;
  if (stages.length === 0) {
    throw new Error('YAML 配置至少需要一个 stages 条目');
  }
  return config;
}

function cloneConfig(config: Record<string, unknown>): Record<string, unknown> {
  return JSON.parse(JSON.stringify(config)) as Record<string, unknown>;
}

function templateConfig(template: PipelineTemplate): Record<string, unknown> {
  if (template.yaml_config) {
    return cloneConfig(template.yaml_config);
  }
  return {
    name: template.name,
    description: template.description,
    version: '1.0',
    stages: template.stages.map((stage) => ({ id: stage, name: stage, agents: [] })),
  };
}

function stringArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(String);
  }
  return typeof value === 'string' && value ? [value] : [];
}

function writeArrayField(lines: string[], key: string, value: unknown) {
  const items = stringArray(value);
  if (items.length > 0) {
    lines.push(`    ${key}: [${items.join(', ')}]`);
  }
}

function writeScalarField(lines: string[], key: string, value: unknown) {
  if (value !== undefined && value !== null && value !== '') {
    lines.push(`    ${key}: ${String(value)}`);
  }
}

function pipelineConfigToYaml(config: Record<string, unknown>, fallbackName: string, fallbackDescription: string): string {
  const lines: string[] = [];
  const name = typeof config.name === 'string' ? config.name : fallbackName;
  const description = typeof config.description === 'string' ? config.description : fallbackDescription;
  lines.push(`name: ${name}`);
  if (description) lines.push(`description: ${description}`);
  if (typeof config.version === 'string') lines.push(`version: ${config.version}`);
  lines.push('stages:');
  const stages = Array.isArray(config.stages) ? config.stages : [];
  for (const stage of stages) {
    if (!stage || typeof stage !== 'object') continue;
    const record = stage as Record<string, unknown>;
    const id = typeof record.id === 'string' ? record.id : '';
    if (!id) continue;
    lines.push(`  - id: ${id}`);
    if (typeof record.name === 'string') lines.push(`    name: ${record.name}`);
    writeScalarField(lines, 'type', record.type);
    writeArrayField(lines, 'agents', record.agents);
    if (record.parallel === true || record.is_parallel === true) lines.push('    parallel: true');
    writeArrayField(lines, 'input', record.input);
    if (record.output && typeof record.output === 'object' && !Array.isArray(record.output)) {
      lines.push('    output:');
      for (const [key, value] of Object.entries(record.output)) {
        lines.push(`      ${key}: ${String(value)}`);
      }
    }
    writeArrayField(lines, 'json_artifacts', record.json_artifacts);
    writeArrayField(lines, 'required_artifacts', record.required_artifacts);
    writeScalarField(lines, 'output_file', record.output_file);
    writeScalarField(lines, 'output_json', record.output_json);
    writeScalarField(lines, 'decision_file', record.decision_file);
    writeScalarField(lines, 'allow_auto_approve', record.allow_auto_approve);
    writeScalarField(lines, 'allow_auto_skip', record.allow_auto_skip);
    writeScalarField(lines, 'requires_reason_on_reject', record.requires_reason_on_reject);
    writeScalarField(lines, 'reject_to', record.reject_to);
    writeScalarField(lines, 'loopback_to', record.loopback_to);
    if (Array.isArray(record.loopback_trigger)) {
      writeArrayField(lines, 'loopback_trigger', record.loopback_trigger);
    } else {
      writeScalarField(lines, 'loopback_trigger', record.loopback_trigger);
    }
    writeScalarField(lines, 'max_retries', record.max_retries);
  }
  return lines.length > 2 ? `${lines.join('\n')}\n` : DEFAULT_YAML;
}

function pipelineToYaml(pipeline: Pipeline | null): string {
  if (!pipeline) return DEFAULT_YAML;
  return pipelineConfigToYaml(pipeline.yaml_config || {}, pipeline.name, pipeline.description);
}

function templateToYaml(template: PipelineTemplate): string {
  return pipelineConfigToYaml(
    templateConfig(template),
    template.name,
    template.description,
  );
}

function PipelineEditorModal({
  pipeline,
  onClose,
  onSaved,
}: {
  pipeline: Pipeline | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(pipeline?.name ?? '');
  const [description, setDescription] = useState(pipeline?.description ?? '');
  const [yaml, setYaml] = useState(pipelineToYaml(pipeline));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function handleSave() {
    if (!name.trim() || !yaml.trim()) {
      setError('名称和 YAML 配置不能为空');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const yamlConfig = parsePipelineYaml(yaml.trim());
      const payload = {
        id: name.trim().toLowerCase().replace(/\s+/g, '-'),
        name: name.trim(),
        description: description.trim(),
        yaml_config: yamlConfig,
      };
      if (pipeline) {
        await updatePipeline(pipeline.id, payload);
      } else {
        await createPipeline(payload);
      }
      onSaved();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modalOverlay" role="dialog" aria-modal="true">
      <div className="modal">
        <div className="modalHeader">
          <h2>{pipeline ? '编辑 Pipeline' : '新建 Pipeline'}</h2>
          <button className="iconButton" onClick={onClose} aria-label="关闭"><X size={16} /></button>
        </div>
        {error && <div className="formError">{error}</div>}
        <label>名称</label>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Pipeline 名称" />
        <label>描述</label>
        <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="简要描述" />
        <label>YAML 配置</label>
        <textarea className="yamlEditor" value={yaml} onChange={(e) => setYaml(e.target.value)} placeholder="Pipeline YAML 配置" />
        <div className="modalActions">
          <button className="button" onClick={onClose}>取消</button>
          <button className="button primary" disabled={saving} onClick={handleSave}>
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}

export function Pipelines() {
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [templates, setTemplates] = useState<PipelineTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingPipeline, setEditingPipeline] = useState<Pipeline | null>(null);

  function load() {
    setLoading(true);
    setError('');
    Promise.all([fetchPipelines(), fetchPipelineTemplates()])
      .then(([p, t]) => { setPipelines(p); setTemplates(t); })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  async function handleDelete(id: string, name: string) {
    if (!window.confirm(`确定删除 Pipeline「${name}」？此操作不可撤销。`)) return;
    try {
      await deletePipeline(id);
      setPipelines((prev) => prev.filter((p) => p.id !== id));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '删除失败');
    }
  }

  function openEditor(pipeline: Pipeline | null) {
    setEditingPipeline(pipeline);
    setEditorOpen(true);
  }

  function useTemplate(template: PipelineTemplate) {
    const pipelineFromTemplate: Pipeline = {
      id: template.id,
      name: template.name,
      description: template.description,
      yaml_config: templateConfig(template),
      stage_count: template.stages.length,
    };
    setEditingPipeline(pipelineFromTemplate);
    setEditorOpen(true);
  }

  if (error) {
    return (
      <div className="page">
        <header className="pageHeader"><h1>Pipeline 模板</h1></header>
        <div className="errorPanel">
          <h2><AlertTriangle size={20} /> 加载失败</h2>
          <p>{error}</p>
          <button className="button primary" onClick={load}>重试</button>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="pageHeader">
        <h1>Pipeline 模板</h1>
        <button className="button primary" onClick={() => openEditor(null)}><Plus size={15} /> 新建 Pipeline</button>
      </header>

      {templates.length > 0 && (
        <section style={{ marginBottom: 24 }}>
          <div className="panelHeader"><h2>内置模板</h2></div>
          <div className="templateGrid">
            {templates.map((template) => (
              <div key={template.id} className="pipelineCard">
                <Boxes size={20} />
                <h2>{template.name}</h2>
                <p>{template.description}</p>
                <div className="pipelineStats">
                  <span>{template.stages.length} 个阶段</span>
                  <span>{template.stages.join(' → ')}</span>
                </div>
                <button className="button" style={{ marginTop: 12 }} onClick={() => useTemplate(template)}>
                  <Plus size={14} /> 使用此模板
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="panel">
        <div className="panelHeader"><h2>自定义 Pipeline</h2></div>
        {loading ? (
          <div className="emptyState">加载中...</div>
        ) : pipelines.length === 0 ? (
          <div className="emptyState">
            <p>暂无自定义 Pipeline</p>
            <small>点击"新建 Pipeline"或使用上方内置模板创建</small>
          </div>
        ) : (
          <div className="tableWrap">
            <table>
              <thead><tr><th>名称</th><th>描述</th><th>Stage 数</th><th>创建时间</th><th>操作</th></tr></thead>
              <tbody>
                {pipelines.map((pipeline) => (
                  <tr key={pipeline.id}>
                    <td className="pipelineName">{pipeline.name}</td>
                    <td className="ellipsis">{pipeline.description}</td>
                    <td>{pipeline.stage_count ?? '-'}</td>
                    <td>{pipeline.created_at ? new Date(pipeline.created_at).toLocaleDateString('zh-CN') : '-'}</td>
                    <td>
                      <div className="tableActions">
                        <button className="iconButton" onClick={() => openEditor(pipeline)} aria-label="编辑"><Edit3 size={14} /></button>
                        <button className="iconButton" onClick={() => handleDelete(pipeline.id, pipeline.name)} aria-label="删除"><Trash2 size={14} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {editorOpen && (
        <PipelineEditorModal
          pipeline={editingPipeline}
          onClose={() => setEditorOpen(false)}
          onSaved={() => load()}
        />
      )}
    </div>
  );
}
