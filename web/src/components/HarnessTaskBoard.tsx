import { Plus } from 'lucide-react';
import { useState } from 'react';
import type { TaskBoardEventRequest, TaskBoardResponse } from '../lib/types';

interface HarnessTaskBoardProps {
  board: TaskBoardResponse | null;
  canEdit: boolean;
  onAppendEvent: (event: TaskBoardEventRequest) => Promise<void>;
}

const STATES = ['planned', 'in_progress', 'blocked', 'qa_failed', 'review_changes_requested', 'rejected', 'cancelled', 'archived'];

export function HarnessTaskBoard({ board, canEdit, onAppendEvent }: HarnessTaskBoardProps) {
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [draft, setDraft] = useState<TaskBoardEventRequest>({
    task_id: '',
    title: '',
    state: 'planned',
    source_stage: 'planning',
    run_id: '',
    artifact_dir: '',
    decision_ids: ['manual:harness-ui'],
    summary: '',
  });

  async function submit() {
    setSaving(true);
    setError('');
    try {
      await onAppendEvent({
        ...draft,
        decision_ids: draft.decision_ids.map((item) => item.trim()).filter(Boolean),
      });
      setShowForm(false);
      setDraft({
        task_id: '',
        title: '',
        state: 'planned',
        source_stage: 'planning',
        run_id: '',
        artifact_dir: '',
        decision_ids: ['manual:harness-ui'],
        summary: '',
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '写入失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="harnessTaskBoard">
      <div className="panelHeader">
        <h2>Task Board</h2>
        {canEdit ? (
          <button className="button" onClick={() => setShowForm((value) => !value)}>
            <Plus size={14} /> 新增事件
          </button>
        ) : null}
      </div>

      <div className="harnessBoardSummary">
        <span className="statMini">Total <strong>{board?.summary.total ?? 0}</strong></span>
        {Object.entries(board?.summary.by_state || {}).map(([state, count]) => (
          <span className="metaTag" key={state}>{state}: {count}</span>
        ))}
      </div>

      {showForm && canEdit ? (
        <div className="harnessEventForm">
          {error ? <div className="formError">{error}</div> : null}
          <div className="harnessFormGrid">
            <label>
              <span>Task ID</span>
              <input value={draft.task_id} onChange={(event) => setDraft({ ...draft, task_id: event.target.value })} />
            </label>
            <label>
              <span>State</span>
              <select value={draft.state} onChange={(event) => setDraft({ ...draft, state: event.target.value })}>
                {STATES.map((state) => <option key={state} value={state}>{state}</option>)}
              </select>
            </label>
            <label>
              <span>Run ID</span>
              <input value={draft.run_id} onChange={(event) => setDraft({ ...draft, run_id: event.target.value })} />
            </label>
            <label>
              <span>Artifact Dir</span>
              <input value={draft.artifact_dir} onChange={(event) => setDraft({ ...draft, artifact_dir: event.target.value })} />
            </label>
          </div>
          <label>
            <span>Title</span>
            <input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
          </label>
          <label>
            <span>Summary</span>
            <textarea value={draft.summary} onChange={(event) => setDraft({ ...draft, summary: event.target.value })} rows={3} />
          </label>
          <label>
            <span>Decision IDs</span>
            <input
              value={draft.decision_ids.join(', ')}
              onChange={(event) => setDraft({ ...draft, decision_ids: event.target.value.split(',') })}
            />
          </label>
          <div className="modalActions">
            <button className="button" onClick={() => setShowForm(false)}>取消</button>
            <button className="button primary" onClick={submit} disabled={saving || !draft.task_id.trim() || !draft.run_id.trim() || !draft.artifact_dir.trim()}>
              保存事件
            </button>
          </div>
        </div>
      ) : null}

      {board && board.tasks.length > 0 ? (
        <div className="harnessTaskList">
          {board.tasks.map((task) => (
            <article className="harnessTaskItem" key={task.id}>
              <div className="harnessTaskMain">
                <span className="badge badge-pending">{task.state}</span>
                <strong>{task.title || task.id}</strong>
                <span className="mono">{task.id}</span>
              </div>
              {task.summary ? <p>{task.summary}</p> : null}
              <div className="harnessTaskMeta">
                {(task.run_ids || []).slice(0, 3).map((id) => <span className="metaTag" key={id}>run {id}</span>)}
                {(task.decision_ids || []).slice(0, 3).map((id) => <span className="metaTag" key={id}>{id}</span>)}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="emptyState">
          <p>暂无 Task Board 记录</p>
        </div>
      )}
    </section>
  );
}
