import { X } from 'lucide-react';
import { useState } from 'react';
import { rememberRunWorkdir, runQuery } from '../lib/api';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function NewRunModal({ open, onClose }: Props) {
  const [workdir, setWorkdir] = useState('/Users/wurui/IdeaProjects/LifeRhythm');
  const [requirement, setRequirement] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    setSubmitting(true);
    try {
      const response = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workdir, requirement, yes: false }),
      });
      if (response.ok) {
        const payload = await response.json();
        rememberRunWorkdir(payload.run_id, workdir);
        window.history.pushState({}, '', `/runs/${payload.run_id}${runQuery(workdir)}`);
        window.dispatchEvent(new PopStateEvent('popstate'));
        onClose();
      }
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
        <label>Pipeline 模板</label>
        <select>
          <option>LifeRhythm 标准交付</option>
          <option>Web 项目标准交付</option>
          <option>后端服务标准交付</option>
        </select>
        <label>项目路径</label>
        <input value={workdir} onChange={(event) => setWorkdir(event.target.value)} />
        <label>需求描述</label>
        <textarea value={requirement} onChange={(event) => setRequirement(event.target.value)} />
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
