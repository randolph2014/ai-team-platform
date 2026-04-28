import { AlertTriangle, FileText, Loader2, RotateCcw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { fetchSettings, resetSettings } from '../lib/api';
import type { SettingsResponse } from '../lib/types';

function renderValue(value: unknown): React.ReactNode {
  if (value === null || value === undefined) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  if (typeof value === 'boolean') return <span style={{ color: value ? 'var(--green)' : 'var(--red)' }}>{value ? 'true' : 'false'}</span>;
  if (typeof value === 'number') return <span style={{ color: 'var(--blue)' }}>{value}</span>;
  if (typeof value === 'string') {
    if (value === '***') return <span style={{ color: 'var(--yellow)' }}>•••••••</span>;
    return value || <span style={{ color: 'var(--text-muted)' }}>—</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span style={{ color: 'var(--text-muted)' }}>[]</span>;
    return (
      <div style={{ marginTop: 4 }}>
        {value.map((item, i) => (
          <div key={i} style={{ padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
            {typeof item === 'object' && item !== null ? renderObject(item as Record<string, unknown>) : renderValue(item)}
          </div>
        ))}
      </div>
    );
  }
  if (typeof value === 'object') return renderObject(value as Record<string, unknown>);
  return String(value);
}

function renderObject(obj: Record<string, unknown>): React.ReactNode {
  return (
    <div className="configEntries">
      {Object.entries(obj).map(([key, val]) => (
        <div key={key} className="configEntry">
          <span className="configKey">{key}</span>
          <span className="configValue">{renderValue(val)}</span>
        </div>
      ))}
    </div>
  );
}

const SECTION_LABELS: Record<string, string> = {
  providers: 'Provider',
  agents: 'Agent 配置',
  pipeline: 'Pipeline',
  runner: 'Runner',
  worktree: 'Worktree',
  quality_gates: '质量门禁',
  context_scanner: '上下文扫描',
  metadata: '元数据',
};

export function Settings() {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');
  const [activeSection, setActiveSection] = useState(0);

  useEffect(() => {
    setLoading(true);
    setError('');
    fetchSettings()
      .then(setSettings)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  function getSections(): Array<{ key: string; value: unknown }> {
    if (!settings?.config) return [];
    return Object.entries(settings.config)
      .filter(([_, v]) => v !== null && v !== undefined)
      .map(([key, value]) => ({ key, value }));
  }

  async function handleReset() {
    setSaving(true);
    setSaveMessage('');
    try {
      const result = await resetSettings();
      setSettings(result);
      setSaveMessage('设置已重置');
    } catch (e: unknown) {
      setSaveMessage(e instanceof Error ? e.message : '重置失败');
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="page">
        <header className="pageHeader"><h1>设置</h1></header>
        <div className="emptyState"><Loader2 size={24} className="spinner" /> 加载中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page">
        <header className="pageHeader"><h1>设置</h1></header>
        <div className="errorPanel">
          <h2><AlertTriangle size={20} /> 加载失败</h2>
          <p>{error}</p>
          <button className="button primary" onClick={() => {
            setError('');
            setLoading(true);
            fetchSettings()
              .then(setSettings)
              .catch((err: Error) => setError(err.message))
              .finally(() => setLoading(false));
          }}>重试</button>
        </div>
      </div>
    );
  }

  if (!settings) return null;

  const sections = getSections();
  const currentSection = sections[activeSection];

  return (
    <div className="page">
      <header className="pageHeader">
        <h1>设置</h1>
        <div className="pageActions">
          <span className="configSource">
            <FileText size={13} /> {settings.source}{settings.path ? ` · ${settings.path}` : ''}
          </span>
          <button className="button" onClick={handleReset} disabled={saving}><RotateCcw size={14} /> 重置为默认</button>
        </div>
      </header>
      {saveMessage && <div className={`saveBanner ${saveMessage.includes('失败') ? 'saveBannerError' : ''}`}>{saveMessage}</div>}
      {settings.warnings.length > 0 && (
        <div className="saveBanner saveBannerError" style={{ marginBottom: 18 }}>
          {settings.warnings.map((w, i) => <p key={i}>{w}</p>)}
        </div>
      )}
      <div className="settingsGrid">
        <aside className="settingsNav">
          {sections.map((section, index) => (
            <a
              key={section.key}
              className={activeSection === index ? 'settingsNavActive' : ''}
              onClick={() => setActiveSection(index)}
            >
              {SECTION_LABELS[section.key] || section.key}
            </a>
          ))}
        </aside>
        <section className="panel">
          {currentSection ? (
            <div className="settingGroup">
              <h2>{SECTION_LABELS[currentSection.key] || currentSection.key}</h2>
              {typeof currentSection.value === 'object' && currentSection.value !== null && !Array.isArray(currentSection.value)
                ? renderObject(currentSection.value as Record<string, unknown>)
                : renderValue(currentSection.value)}
            </div>
          ) : (
            <div className="emptyState">无配置数据</div>
          )}
        </section>
      </div>
    </div>
  );
}
