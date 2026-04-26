import { Edit3, Plus, Trash2, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { createPipeline, deletePipeline, fetchPipelines, updatePipeline } from '../lib/api';
import type { Pipeline } from '../lib/types';

const DEFAULT_YAML = `name: my-pipeline
description: A new pipeline
stages:
  - id: plan
    name: 方案讨论
    agents: [brainstormer, devils-advocate]
  - id: develop
    name: 开发
    agents: [tech-lead]
  - id: verify
    name: 测试审查
    agents: [qa, reviewer]
`;

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
  const [yaml, setYaml] = useState(pipeline?.yaml ?? DEFAULT_YAML);
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
      const payload = { name: name.trim(), description: description.trim(), yaml: yaml.trim() };
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
  const [loading, setLoading] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingPipeline, setEditingPipeline] = useState<Pipeline | null>(null);

  function load() {
    setLoading(true);
    fetchPipelines()
      .then(setPipelines)
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  async function handleDelete(id: string) {
    try {
      await deletePipeline(id);
      setPipelines((prev) => prev.filter((p) => p.id !== id));
    } catch {
      // silently fail
    }
  }

  function openEditor(pipeline: Pipeline | null) {
    setEditingPipeline(pipeline);
    setEditorOpen(true);
  }

  return (
    <div className="page">
      <header className="pageHeader">
        <h1>Pipeline 模板</h1>
        <button className="button primary" onClick={() => openEditor(null)}><Plus size={15} /> 新建 Pipeline</button>
      </header>
      {loading ? (
        <div className="emptyState">加载中...</div>
      ) : pipelines.length === 0 ? (
        <div className="emptyState">
          <p>暂无 Pipeline 模板</p>
          <small>点击"新建 Pipeline"创建第一个模板</small>
        </div>
      ) : (
        <section className="panel">
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
                        <button className="iconButton" onClick={() => handleDelete(pipeline.id)} aria-label="删除"><Trash2 size={14} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

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
