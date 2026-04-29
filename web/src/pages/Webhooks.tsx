import { Loader2, Plus, Trash2, WebhookIcon } from 'lucide-react';
import { useEffect, useState } from 'react';
import { createWebhook, deleteWebhook, fetchWebhooks } from '../lib/api';
import type { Webhook } from '../lib/types';

const EVENTS = ['push', 'pull_request', 'issue_comment', 'merge_request', 'tag_push'];

export function Webhooks() {
  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  const [form, setForm] = useState({ url: '', secret: '', events: ['push'], pipeline_id: '' });

  function load() {
    setLoading(true);
    setError('');
    fetchWebhooks()
      .then(setWebhooks)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  function handleCreate() {
    setSaving(true);
    setFormError('');
    createWebhook({
      url: form.url,
      secret: form.secret,
      events: form.events,
      pipeline_id: form.pipeline_id || undefined,
    })
      .then(() => {
        setShowForm(false);
        setForm({ url: '', secret: '', events: ['push'], pipeline_id: '' });
        load();
      })
      .catch((err: Error) => setFormError(err.message))
      .finally(() => setSaving(false));
  }

  function handleDelete(id: string) {
    deleteWebhook(id)
      .then(() => load())
      .catch((err: Error) => setError(err.message));
  }

  return (
    <div className="page">
      <header className="pageHeader">
        <h1>Webhook 管理</h1>
        <button className="button primary" onClick={() => setShowForm(true)}>
          <Plus size={15} /> 新建 Webhook
        </button>
      </header>

      {error && (
        <div className="formError">
          {error}
        </div>
      )}

      {showForm && (
        <section className="panel" style={{ marginBottom: 18 }}>
          <h2 style={{ marginBottom: 14 }}>新建 Webhook</h2>
          {formError && <div className="formError">{formError}</div>}
          <div className="webhookForm">
            <label>
              URL
              <input
                type="text"
                placeholder="https://example.com/webhook"
                value={form.url}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
              />
            </label>
            <label>
              Secret
              <input
                type="text"
                placeholder="webhook secret"
                value={form.secret}
                onChange={(e) => setForm({ ...form, secret: e.target.value })}
              />
            </label>
            <label>
              事件类型
              <div className="webhookEventsCheck">
                {EVENTS.map((ev) => (
                  <label key={ev} className="webhookEventLabel">
                    <input
                      type="checkbox"
                      checked={form.events.includes(ev)}
                      onChange={() => {
                        setForm({
                          ...form,
                          events: form.events.includes(ev)
                            ? form.events.filter((e) => e !== ev)
                            : [...form.events, ev],
                        });
                      }}
                    />{' '}
                    {ev}
                  </label>
                ))}
              </div>
            </label>
            <label>
              Pipeline ID <small>(可选)</small>
              <input
                type="text"
                placeholder="仅触发特定 Pipeline"
                value={form.pipeline_id}
                onChange={(e) => setForm({ ...form, pipeline_id: e.target.value })}
              />
            </label>
            <div className="webhookFormActions">
              <button className="button" onClick={() => setShowForm(false)}>取消</button>
              <button
                className="button primary"
                onClick={handleCreate}
                disabled={saving || !form.url || !form.secret}
              >
                {saving ? '创建中...' : '创建'}
              </button>
            </div>
          </div>
        </section>
      )}

      <section className="panel">
        {loading ? (
          <div className="emptyState"><Loader2 size={24} className="spin" /> 加载中...</div>
        ) : webhooks.length === 0 ? (
          <div className="emptyState">
            <WebhookIcon size={32} />
            <p>暂无 Webhook</p>
            <small>点击"新建 Webhook"按钮创建</small>
          </div>
        ) : (
          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>URL</th>
                  <th>事件</th>
                  <th>Pipeline</th>
                  <th>状态</th>
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {webhooks.map((wh) => (
                  <tr key={wh.id}>
                    <td className="mono" style={{ maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {wh.url}
                    </td>
                    <td>
                      <div className="webhookEventTags">
                        {wh.events.map((ev) => (
                          <span key={ev} className="stageTag">{ev}</span>
                        ))}
                      </div>
                    </td>
                    <td>{wh.pipeline_id || '—'}</td>
                    <td>
                      <span className={`badge ${wh.enabled ? 'badge-completed' : 'badge-failed'}`}>
                        {wh.enabled ? '启用' : '禁用'}
                      </span>
                    </td>
                    <td>{wh.created_at ? new Date(wh.created_at).toLocaleString('zh-CN') : '-'}</td>
                    <td>
                      <div className="tableActions">
                        <button
                          className="iconButton danger"
                          title="删除"
                          onClick={(e) => { e.stopPropagation(); handleDelete(wh.id); }}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
