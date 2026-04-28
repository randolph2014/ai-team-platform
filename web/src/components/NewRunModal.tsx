import { X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { apiFetch, fetchPipelines, rememberRunWorkdir, runQuery } from '../lib/api';
import type { Pipeline } from '../lib/types';

interface Props {
  open: boolean;
  onClose: () => void;
  onRefreshNeeded: () => void;
}

export function NewRunModal({ open, onClose, onRefreshNeeded }: Props) {
  const [workdir, setWorkdir] = useState('');
  const [requirement, setRequirement] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [selectedPipeline, setSelectedPipeline] = useState('');
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (open) {
      setSelectedPipeline('');
      fetchPipelines()
        .then((list) => {
          setPipelines(list);
          if (list.length > 0) {
            setSelectedPipeline(list[0].name);
          }
        })
        .catch(() => undefined);
      setError('');
      setValidationErrors({});
    }
  }, [open]);

  function validate(): boolean {
    const errors: Record<string, string> = {};
    if (!workdir.trim()) errors.workdir = '项目路径不能为空';
    if (!requirement.trim()) errors.requirement = '需求描述不能为空';
    setValidationErrors(errors);
    return Object.keys(errors).length === 0;
  }

  async function submit() {
    if (!validate()) return;
    setSubmitting(true);
    setError('');
    try {
      const response = await apiFetch('/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workdir: workdir.trim(), requirement: requirement.trim(), pipeline: selectedPipeline || undefined, yes: false }),
      });
      if (!response.ok) {
        const body = await response.text();
        throw new Error(body || `HTTP ${response.status}`);
      }
      const payload = await response.json();
      rememberRunWorkdir(payload.run_id, workdir.trim());
      onRefreshNeeded();
      window.history.pushState({}, '', `/runs/${payload.run_id}${runQuery(workdir.trim())}`);
      window.dispatchEvent(new PopStateEvent('popstate'));
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '创建运行失败，请重试');
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) return null;
  return (
    <div className="modalOverlay" role="dialog" aria-modal="true">
      <div className="modal">
        <div className="modalHeader">
          <h2>新建运行</h2>
          <button className="iconButton" onClick={onClose} aria-label="关闭">
            <X size={16} />
          </button>
        </div>
        {error && <div className="formError">{error}</div>}
        <label>Pipeline 模板</label>
        {pipelines.length > 0 ? (
          <>
            <select value={selectedPipeline} onChange={(event) => setSelectedPipeline(event.target.value)}>
              {pipelines.map((pipeline) => (
                <option key={pipeline.id} value={pipeline.name}>{pipeline.name}</option>
              ))}
            </select>
            {validationErrors.pipeline && <span className="fieldError">{validationErrors.pipeline}</span>}
          </>
        ) : (
          <select disabled>
            <option>无可用模板</option>
          </select>
        )}
        <label>项目路径</label>
        <input value={workdir} onChange={(event) => setWorkdir(event.target.value)} />
        {validationErrors.workdir && <span className="fieldError">{validationErrors.workdir}</span>}
        <label>需求描述</label>
        <textarea value={requirement} onChange={(event) => setRequirement(event.target.value)} />
        {validationErrors.requirement && <span className="fieldError">{validationErrors.requirement}</span>}
        <div className="modalActions">
          <button className="button" onClick={onClose}>取消</button>
          <button className="button primary" disabled={!requirement.trim() || submitting} onClick={submit}>
            {submitting ? '创建中' : '开始运行'}
          </button>
        </div>
      </div>
    </div>
  );
}
