import { AlertTriangle, ArrowLeft, Boxes, ChevronDown, ChevronRight, Download, Plus, Save, Wand2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Background,
  BackgroundVariant,
  ConnectionLineType,
  Controls,
  MiniMap,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { AgentNode } from '../components/flow/AgentNode';
import { GateNode } from '../components/flow/GateNode';
import { LoopbackEdge } from '../components/flow/LoopbackEdge';
import { StageNode } from '../components/flow/StageNode';
import { fetchPipelines, fetchPipelineTemplates } from '../lib/api';
import {
  StageSchema,
  type PipelineConfig,
  type StageConfig,
} from '../lib/pipelineSchema';
import type { Pipeline, PipelineTemplate } from '../lib/types';

const NODE_TYPES = { stage: StageNode, agent: AgentNode, gate: GateNode };
const EDGE_TYPES = { loopback: LoopbackEdge };

const STAGE_COLORS = [
  'var(--accent)', 'var(--green)', 'var(--blue)',
  'var(--yellow)', 'var(--purple)', 'var(--red)',
];

type ViewMode = 'canvas' | 'yaml';
type AgentDefWithRuntime = NonNullable<StageConfig['agent_defs']>[number];

function agentRuntime(agent: AgentDefWithRuntime): string {
  return agent.runtime_id || 'auto';
}

function normalizeAgentRuntime(agent: AgentDefWithRuntime): AgentDefWithRuntime {
  return {
    ...agent,
    runtime_id: agentRuntime(agent),
  };
}

function normalizeStagesForRuntime(stages: StageConfig[]): StageConfig[] {
  return stages.map((stage) => {
    const agentDefs = (stage.agent_defs || []).map((agent) => normalizeAgentRuntime(agent as AgentDefWithRuntime));
    return agentDefs.length > 0 ? { ...stage, agent_defs: agentDefs } : stage;
  }) as unknown as StageConfig[];
}

function stagesForSave(stages: StageConfig[]): StageConfig[] {
  return stages.map((stage) => ({
    ...stage,
    agent_defs: stage.agent_defs?.map((agent) => normalizeAgentRuntime(agent as AgentDefWithRuntime)),
  })) as unknown as StageConfig[];
}

function navigate(path: string) {
  window.history.pushState({}, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

function defaultPipeline(): PipelineConfig {
  return {
    name: '新建 Pipeline',
    description: '',
    version: '1.0',
    stages: [
      { id: 'plan', name: '需求分析', agents: [], is_parallel: false },
      { id: 'develop', name: '代码实现', agents: [], is_parallel: false },
    ],
  };
}

function pipelineConfigData(pipeline: Pipeline): Record<string, unknown> {
  return pipeline.yaml_config || {};
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback;
}

function configToYaml(config: PipelineConfig): string {
  const lines: string[] = [];
  lines.push(`name: ${config.name}`);
  if (config.description) lines.push(`description: ${config.description}`);
  lines.push('stages:');
  for (const stage of config.stages) {
    lines.push(`  - id: ${stage.id}`);
    lines.push(`    name: ${stage.name}`);
    if (stage.agents.length > 0) {
      lines.push(`    agents: [${stage.agents.join(', ')}]`);
    }
    if (stage.is_parallel) lines.push(`    is_parallel: true`);
    if (stage.input) lines.push(`    input: ${stage.input}`);
    if (stage.output) {
      lines.push(`    output:`);
      for (const [k, v] of Object.entries(stage.output)) {
        lines.push(`      ${k}: ${v}`);
      }
    }
    if (stage.loopback) {
      lines.push(`    loopback:`);
      lines.push(`      on: ${stage.loopback.on}`);
      lines.push(`      to: ${stage.loopback.to}`);
      lines.push(`      max_retries: ${stage.loopback.max_retries}`);
    }
    if (stage.quality_gates && stage.quality_gates.length > 0) {
      lines.push(`    quality_gates:`);
      for (const gate of stage.quality_gates) {
        lines.push(`      - name: ${gate.name}`);
        lines.push(`        type: ${gate.type}`);
        if (gate.command) lines.push(`        command: ${gate.command}`);
        if (gate.threshold) lines.push(`        threshold: ${gate.threshold}`);
        lines.push(`        required: ${gate.required}`);
      }
    }
    if (stage.agent_defs && stage.agent_defs.length > 0) {
      lines.push(`    agent_defs:`);
      for (const agent of stage.agent_defs) {
        const runtimeId = agentRuntime(agent as AgentDefWithRuntime);
        lines.push(`      - name: ${agent.name}`);
        lines.push(`        runtime_id: ${runtimeId}`);
      }
    }
  }
  return lines.join('\n');
}

function stageToNodes(
  stage: StageConfig,
  index: number,
  stageCount: number,
  loopbackTargets: Map<string, string>,
): Node[] {
  const nodes: Node[] = [];
  const x = 300;
  const y = 80 + index * 180;

  nodes.push({
    id: `stage-${stage.id}`,
    type: 'stage',
    position: { x, y },
    data: {
      name: stage.name,
      status: 'pending',
      is_parallel: stage.is_parallel,
      agentCount: (stage.agents || []).length + (stage.agent_defs?.length || 0),
      hasLoopback: !!stage.loopback,
    },
  });

  if (stage.agent_defs && stage.agent_defs.length > 0) {
    stage.agent_defs.forEach((agent, ai) => {
      nodes.push({
        id: `agent-${stage.id}-${agent.name}`,
        type: 'agent',
        position: { x: x + 220, y: y + ai * 60 - ((stage.agent_defs?.length || 1) - 1) * 30 },
        data: {
          name: agent.name,
          runtime_id: agentRuntime(agent as AgentDefWithRuntime),
          role: agent.role,
          status: 'pending',
        },
      });
    });
  }

  if (stage.quality_gates && stage.quality_gates.length > 0) {
    stage.quality_gates.forEach((gate, gi) => {
      nodes.push({
        id: `gate-${stage.id}-${gate.name}`,
        type: 'gate',
        position: { x: x - 180, y: y + gi * 50 - ((stage.quality_gates?.length || 1) - 1) * 25 },
        data: {
          name: gate.name,
          gateType: gate.type,
          status: 'pending',
          required: gate.required,
          command: gate.command,
        },
      });
    });
  }

  return nodes;
}

function configToEdges(config: PipelineConfig): Edge[] {
  const edges: Edge[] = [];
  const stageIds = config.stages.map((s) => s.id);
  const loopbackEdges: Map<string, { targetId: string; trigger: string; maxRetries: number }> = new Map();

  for (const stage of config.stages) {
    if (stage.loopback) {
      const targetStage = config.stages.find((s) => s.id === stage.loopback!.to);
      if (targetStage) {
        loopbackEdges.set(stage.id, {
          targetId: targetStage.id,
          trigger: stage.loopback.on,
          maxRetries: stage.loopback.max_retries || 3,
        });
      }
    }
  }

  for (let i = 0; i < config.stages.length - 1; i++) {
    edges.push({
      id: `edge-${config.stages[i].id}-${config.stages[i + 1].id}`,
      source: `stage-${config.stages[i].id}`,
      target: `stage-${config.stages[i + 1].id}`,
      type: 'smoothstep',
      animated: true,
      style: { stroke: 'var(--border-light)', strokeWidth: 1.5 },
    });
  }

  for (const [sourceStageId, loopback] of loopbackEdges) {
    edges.push({
      id: `loopback-${sourceStageId}-${loopback.targetId}`,
      source: `stage-${sourceStageId}`,
      target: `stage-${loopback.targetId}`,
      type: 'loopback',
      data: {
        trigger: loopback.trigger,
        maxRetries: loopback.maxRetries,
        retryCount: 0,
      },
    });
  }

  for (const stage of config.stages) {
    if (stage.agent_defs) {
      for (const agent of stage.agent_defs) {
        edges.push({
          id: `edge-${stage.id}-agent-${agent.name}`,
          source: `stage-${stage.id}`,
          target: `agent-${stage.id}-${agent.name}`,
          type: 'smoothstep',
          style: { stroke: 'var(--text-muted)', strokeWidth: 1, strokeDasharray: '4 2' },
        });
      }
    }
    if (stage.quality_gates) {
      for (const gate of stage.quality_gates) {
        edges.push({
          id: `edge-${stage.id}-gate-${gate.name}`,
          source: `gate-${stage.id}-${gate.name}`,
          target: `stage-${stage.id}`,
          type: 'smoothstep',
          style: { stroke: gate.required ? 'var(--yellow)' : 'var(--text-muted)', strokeWidth: 1, strokeDasharray: '4 2' },
        });
      }
    }
  }

  return edges;
}

function useConfigToFlow(config: PipelineConfig) {
  const initialNodes = useMemo(() => {
    const loopbackTargets = new Map<string, string>();
    for (const stage of config.stages) {
      if (stage.loopback) loopbackTargets.set(stage.id, stage.loopback.to);
    }
    return config.stages.flatMap((stage, i) => stageToNodes(stage, i, config.stages.length, loopbackTargets));
  }, [config]);

  const initialEdges = useMemo(() => configToEdges(config), [config]);

  return { initialNodes, initialEdges };
}

export function PipelineEditor({ pipelineId }: { pipelineId?: string }) {
  const [config, setConfig] = useState<PipelineConfig>(defaultPipeline());
  const [selectedStage, setSelectedStage] = useState<StageConfig | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('canvas');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [templates, setTemplates] = useState<PipelineTemplate[]>([]);
  const [templatesOpen, setTemplatesOpen] = useState(false);

  const { initialNodes, initialEdges } = useConfigToFlow(config);
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  useEffect(() => {
    if (pipelineId) {
      setLoading(true);
      fetchPipelines()
        .then((pipelines) => {
          const found = pipelines.find((p: Pipeline) => p.id === pipelineId);
          if (found) {
            try {
              const parsed = pipelineConfigData(found);
              const result = StageSchema.array().safeParse(parsed.stages || []);
              if (result.success) {
                setConfig({
                  name: found.name || stringValue(parsed.name, 'Pipeline'),
                  description: found.description || stringValue(parsed.description, ''),
                  version: stringValue(parsed.version, '1.0'),
                  stages: normalizeStagesForRuntime(result.data),
                });
              } else {
                setConfig({
                  name: found.name || 'Pipeline',
                  description: found.description || '',
                  version: '1.0',
                  stages: [],
                });
              }
            } catch {
              setConfig({
                name: found.name || 'Pipeline',
                description: found.description || '',
                version: '1.0',
                stages: [
                  { id: 'plan', name: '需求分析', agents: [], is_parallel: false },
                  { id: 'develop', name: '代码实现', agents: [], is_parallel: false },
                ],
              });
            }
          }
        })
        .catch((err: Error) => setError(err.message))
        .finally(() => setLoading(false));
    }
  }, [pipelineId]);

  useEffect(() => {
    fetchPipelineTemplates().then(setTemplates).catch(() => {});
  }, []);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges],
  );

  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      const stageId = node.id.startsWith('stage-') ? node.id.replace('stage-', '') : '';
      const stage = config.stages.find((s) => s.id === stageId) || null;
      setSelectedStage(stage);
    },
    [config.stages],
  );

  function handleAddStage() {
    const newId = `stage-${Date.now()}`;
    const newStage: StageConfig = {
      id: newId,
      name: `新阶段 ${config.stages.length + 1}`,
      agents: [],
      is_parallel: false,
    };
    const updated = { ...config, stages: [...config.stages, newStage] };
    setConfig(updated);
  }

  function handleRemoveStage(stageId: string) {
    const updated = {
      ...config,
      stages: config.stages.filter((s) => s.id !== stageId),
    };
    setConfig(updated);
    if (selectedStage?.id === stageId) setSelectedStage(null);
  }

  function handleStageUpdate(field: string, value: unknown) {
    if (!selectedStage) return;
    const updatedStages = config.stages.map((s) =>
      s.id === selectedStage.id ? { ...s, [field]: value } : s,
    );
    const updated = { ...config, stages: updatedStages };
    setConfig(updated);
    setSelectedStage({ ...selectedStage, [field]: value });
  }

  function handleAddAgent() {
    if (!selectedStage) return;
    const agentDefs = selectedStage.agent_defs || [];
    const newAgent = {
      name: `agent-${agentDefs.length + 1}`,
      runtime_id: 'auto',
    };
    const updatedDefs = [...agentDefs, newAgent];
    handleStageUpdate('agent_defs', updatedDefs);
  }

  function handleRemoveAgent(agentName: string) {
    if (!selectedStage?.agent_defs) return;
    const updatedDefs = selectedStage.agent_defs.filter((a) => a.name !== agentName);
    handleStageUpdate('agent_defs', updatedDefs);
  }

  function handleAddGate() {
    if (!selectedStage) return;
    const gates = selectedStage.quality_gates || [];
    const newGate = {
      name: `gate-${gates.length + 1}`,
      type: 'command' as const,
      required: true,
    };
    const updatedGates = [...gates, newGate];
    handleStageUpdate('quality_gates', updatedGates);
  }

  function handleRemoveGate(gateName: string) {
    if (!selectedStage?.quality_gates) return;
    const updatedGates = selectedStage.quality_gates.filter((g) => g.name !== gateName);
    handleStageUpdate('quality_gates', updatedGates);
  }

  function handleUseTemplate(template: PipelineTemplate) {
    const stages: StageConfig[] = template.stages.map((s: string) => ({
      id: s,
      name: s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
      agents: [],
      is_parallel: false,
    }));
    setConfig({
      name: template.name,
      description: template.description,
      version: '1.0',
      stages,
    });
    setTemplatesOpen(false);
  }

  async function handleSave() {
    setSaving(true);
    setError('');
    try {
      const stages = stagesForSave(config.stages);
      const id = config.name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '');
      const response = await fetch('/api/pipelines', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id,
          name: config.name,
          description: config.description,
          yaml_config: {
            name: config.name,
            description: config.description,
            version: config.version,
            stages,
          },
        }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({ detail: '保存失败' }));
        throw new Error(body.detail || `保存失败: ${response.status}`);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  function handleExportYaml() {
    const yaml = configToYaml(config);
    const blob = new Blob([yaml], { type: 'text/yaml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${config.name.toLowerCase().replace(/\s+/g, '-')}.yaml`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const yamlOutput = configToYaml(config);

  if (loading) {
    return (
      <div className="page">
        <header className="pageHeader"><h1>Pipeline 编辑器</h1></header>
        <div className="emptyState">加载中...</div>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="pageHeader">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button className="iconButton" onClick={() => navigate('/pipelines')} aria-label="返回">
            <ArrowLeft size={16} />
          </button>
          <h1>{pipelineId ? '编辑 Pipeline' : '新建 Pipeline'}</h1>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            className="button"
            onClick={() => setTemplatesOpen(!templatesOpen)}
          >
            <Boxes size={14} /> 模板
          </button>
          <button
            className="button"
            onClick={() => setViewMode(viewMode === 'canvas' ? 'yaml' : 'canvas')}
          >
            {viewMode === 'canvas' ? <Wand2 size={14} /> : <Wand2 size={14} />}
            {' '}{viewMode === 'canvas' ? 'YAML' : '画布'}
          </button>
          <button className="button" onClick={handleExportYaml}>
            <Download size={14} /> 导出
          </button>
          <button className="button primary" disabled={saving} onClick={handleSave}>
            <Save size={14} /> {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </header>

      {error && (
        <div className="errorPanel">
          <h2><AlertTriangle size={20} /> 错误</h2>
          <p>{error}</p>
          <button className="button" onClick={() => setError('')}>关闭</button>
        </div>
      )}

      {templatesOpen && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <div className="panelHeader">
            <h2>内置模板</h2>
            <button className="iconButton" onClick={() => setTemplatesOpen(false)}>×</button>
          </div>
          <div className="templateGrid">
            {templates.map((tpl) => (
              <div key={tpl.id} className="pipelineCard">
                <Boxes size={20} />
                <h2>{tpl.name}</h2>
                <p>{tpl.description}</p>
                <div className="pipelineStats">
                  <span>{tpl.stages.length} 个阶段</span>
                  <span>{tpl.stages.join(' → ')}</span>
                </div>
                <button
                  className="button"
                  style={{ marginTop: 12 }}
                  onClick={() => handleUseTemplate(tpl)}
                >
                  <Plus size={14} /> 使用此模板
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="pipeline-editor-layout">
        <div className="pipeline-editor-canvas">
          {viewMode === 'canvas' ? (
            <div className="pipeline-editor-flow">
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onNodeClick={onNodeClick}
                nodeTypes={NODE_TYPES}
                edgeTypes={EDGE_TYPES}
                connectionLineType={ConnectionLineType.SmoothStep}
                fitView
                minZoom={0.2}
                maxZoom={2}
                defaultEdgeOptions={{
                  type: 'smoothstep',
                  animated: true,
                }}
              >
                <Controls />
                <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="var(--border)" />
                <MiniMap
                  nodeStrokeColor="var(--border-light)"
                  nodeColor={(n) => {
                    const idx = config.stages.findIndex((s) => `stage-${s.id}` === n.id);
                    return STAGE_COLORS[idx % STAGE_COLORS.length] || 'var(--accent)';
                  }}
                  style={{ background: 'var(--bg-secondary)' }}
                />
              </ReactFlow>
            </div>
          ) : (
            <div className="pipeline-editor-yaml-view">
              <div className="panelHeader"><h2>YAML 预览</h2></div>
              <pre className="yamlPreview">{yamlOutput}</pre>
            </div>
          )}

          <div className="pipeline-editor-toolbar">
            <button className="button primary" onClick={handleAddStage}>
              <Plus size={14} /> 添加阶段
            </button>
            <span className="pipeline-editor-stage-count">
              {config.stages.length} 个阶段
            </span>
          </div>
        </div>

        {sidebarOpen && (
          <aside className="pipeline-editor-sidebar">
            <div className="panelHeader">
              <h2>属性面板</h2>
              <button
                className="iconButton"
                onClick={() => setSidebarOpen(false)}
                aria-label="关闭属性面板"
              >
                ×
              </button>
            </div>

            <div className="pipeline-editor-properties">
              <label>Pipeline 名称</label>
              <input
                value={config.name}
                onChange={(e) => setConfig({ ...config, name: e.target.value })}
                placeholder="Pipeline 名称"
              />

              <label>描述</label>
              <input
                value={config.description}
                onChange={(e) => setConfig({ ...config, description: e.target.value })}
                placeholder="简要描述"
              />

              {selectedStage ? (
                <div className="pipeline-editor-stage-props">
                  <div className="pipeline-editor-section-header">
                    <h3>{selectedStage.name}</h3>
                    <button
                      className="iconButton"
                      onClick={() => handleRemoveStage(selectedStage.id)}
                      aria-label="删除阶段"
                      style={{ color: 'var(--red)' }}
                    >
                      ×
                    </button>
                  </div>

                  <label>Stage ID</label>
                  <input
                    value={selectedStage.id}
                    onChange={(e) => handleStageUpdate('id', e.target.value)}
                  />

                  <label>名称</label>
                  <input
                    value={selectedStage.name}
                    onChange={(e) => handleStageUpdate('name', e.target.value)}
                  />

                  <label>
                    <input
                      type="checkbox"
                      checked={selectedStage.is_parallel}
                      onChange={(e) => handleStageUpdate('is_parallel', e.target.checked)}
                    />
                    {' '}并行执行
                  </label>

                  <label>Input</label>
                  <input
                    value={selectedStage.input || ''}
                    onChange={(e) => handleStageUpdate('input', e.target.value || undefined)}
                    placeholder="如: requirement"
                  />

                  <details className="pipeline-editor-detail">
                    <summary>Agents ({(selectedStage.agent_defs || []).length})</summary>
                    <div className="pipeline-editor-detail-content">
                      {(selectedStage.agent_defs || []).map((agent) => (
                        <div key={agent.name} className="pipeline-editor-list-item">
                          <div>
                            <strong>{agent.name}</strong>
                            <span className="flow-node-tag">{agentRuntime(agent as AgentDefWithRuntime)}</span>
                          </div>
                          <button className="iconButton" onClick={() => handleRemoveAgent(agent.name)}>×</button>
                        </div>
                      ))}
                      <button className="button" onClick={handleAddAgent}><Plus size={12} /> 添加 Agent</button>
                    </div>
                  </details>

                  <details className="pipeline-editor-detail">
                    <summary>Quality Gates ({(selectedStage.quality_gates || []).length})</summary>
                    <div className="pipeline-editor-detail-content">
                      {(selectedStage.quality_gates || []).map((gate) => (
                        <div key={gate.name} className="pipeline-editor-list-item">
                          <div>
                            <strong>{gate.name}</strong>
                            <span className="flow-node-tag">{gate.type}</span>
                            {gate.required && <span className="flow-node-tag">必要</span>}
                          </div>
                          <button className="iconButton" onClick={() => handleRemoveGate(gate.name)}>×</button>
                        </div>
                      ))}
                      <button className="button" onClick={handleAddGate}><Plus size={12} /> 添加 Gate</button>
                    </div>
                  </details>

                  <details className="pipeline-editor-detail">
                    <summary>Loopback 回环</summary>
                    <div className="pipeline-editor-detail-content">
                      <label>触发条件 (on)</label>
                      <input
                        value={selectedStage.loopback?.on || ''}
                        onChange={(e) => handleStageUpdate('loopback', {
                          ...selectedStage.loopback,
                          on: e.target.value,
                          to: selectedStage.loopback?.to || config.stages[0]?.id || '',
                          max_retries: selectedStage.loopback?.max_retries || 3,
                        })}
                        placeholder="如: qa 输出含 FAILED"
                      />
                      <label>回退到 (to)</label>
                      <select
                        value={selectedStage.loopback?.to || ''}
                        onChange={(e) => handleStageUpdate('loopback', {
                          ...selectedStage.loopback,
                          on: selectedStage.loopback?.on || 'qa-failed',
                          to: e.target.value,
                          max_retries: selectedStage.loopback?.max_retries || 3,
                        })}
                      >
                        <option value="">-- 选择目标 Stage --</option>
                        {config.stages.filter((s) => s.id !== selectedStage.id).map((s) => (
                          <option key={s.id} value={s.id}>{s.name}</option>
                        ))}
                      </select>
                      <label>最大重试次数</label>
                      <input
                        type="number"
                        min={1}
                        max={10}
                        value={selectedStage.loopback?.max_retries || 3}
                        onChange={(e) => handleStageUpdate('loopback', {
                          ...selectedStage.loopback,
                          on: selectedStage.loopback?.on || 'qa-failed',
                          to: selectedStage.loopback?.to || config.stages[0]?.id || '',
                          max_retries: parseInt(e.target.value, 10) || 3,
                        })}
                      />
                    </div>
                  </details>
                </div>
              ) : (
                <div className="emptyState" style={{ marginTop: 16 }}>
                  <p>点击画布中的节点查看属性</p>
                </div>
              )}
            </div>
          </aside>
        )}

        {!sidebarOpen && (
          <button
            className="pipeline-editor-sidebar-toggle"
            onClick={() => setSidebarOpen(true)}
            aria-label="打开属性面板"
          >
            <ChevronRight size={16} />
          </button>
        )}
      </div>
    </div>
  );
}
