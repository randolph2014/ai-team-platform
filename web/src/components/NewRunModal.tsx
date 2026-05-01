import { X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { createRun, fetchPipelineTemplates, fetchPipelines, rememberRunWorkdir, runQuery } from '../lib/api';
import type { Pipeline, PipelineTemplate } from '../lib/types';

interface Props {
  open: boolean;
  onClose: () => void;
  onRefreshNeeded: () => void;
}

interface PipelineChoice {
  ref: string;
  name: string;
  description: string;
  source: 'template' | 'pipeline';
}

function templateChoice(template: PipelineTemplate): PipelineChoice {
  return {
    ref: `template:${template.id}`,
    name: template.name,
    description: template.description,
    source: 'template',
  };
}

function customPipelineChoice(pipeline: Pipeline): PipelineChoice {
  return {
    ref: `pipeline:${pipeline.id}`,
    name: pipeline.name,
    description: pipeline.description,
    source: 'pipeline',
  };
}

export function NewRunModal({ open, onClose, onRefreshNeeded }: Props) {
  const [workdir, setWorkdir] = useState('');
  const [requirement, setRequirement] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [pipelineChoices, setPipelineChoices] = useState<PipelineChoice[]>([]);
  const [selectedPipeline, setSelectedPipeline] = useState('');
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (open) {
      setSelectedPipeline('');
      Promise.all([fetchPipelineTemplates(), fetchPipelines()])
        .then(([templates, pipelines]) => {
          const choices = [
            ...templates.map(templateChoice),
            ...pipelines.map(customPipelineChoice),
          ];
          setPipelineChoices(choices);
          if (choices.length > 0) {
            setSelectedPipeline(choices[0].ref);
          }
        })
        .catch((e: Error) => setError(e.message || '加载 Pipeline 模板失败'));
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
      const payload = await createRun(
        workdir.trim(),
        requirement.trim(),
        selectedPipeline ? { pipeline_id: selectedPipeline } : undefined,
      );
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
        <label htmlFor="new-run-pipeline">Pipeline 模板</label>
        {pipelineChoices.length > 0 ? (
          <>
            <select id="new-run-pipeline" value={selectedPipeline} onChange={(event) => setSelectedPipeline(event.target.value)}>
              {pipelineChoices.map((choice) => (
                <option key={choice.ref} value={choice.ref}>{choice.name}</option>
              ))}
            </select>
            {validationErrors.pipeline && <span className="fieldError">{validationErrors.pipeline}</span>}
          </>
        ) : (
          <select disabled>
            <option>无可用模板</option>
          </select>
        )}
        <label htmlFor="new-run-workdir">项目路径</label>
        <input id="new-run-workdir" value={workdir} onChange={(event) => setWorkdir(event.target.value)} />
        {validationErrors.workdir && <span className="fieldError">{validationErrors.workdir}</span>}
        <label htmlFor="new-run-requirement">需求描述</label>
        <textarea id="new-run-requirement" value={requirement} onChange={(event) => setRequirement(event.target.value)} />
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
