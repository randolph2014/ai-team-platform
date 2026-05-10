import { AlertTriangle, Play, RefreshCw, Save, ShieldCheck } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ProjectSelector } from '../components/ProjectSelector';
import { HarnessAssetEditor } from '../components/HarnessAssetEditor';
import { HarnessConflictDialog } from '../components/HarnessConflictDialog';
import { HarnessTaskBoard } from '../components/HarnessTaskBoard';
import {
  ApiError,
  appendTaskBoardEvent,
  fetchHarness,
  fetchTaskBoard,
  runHarnessChecks,
  saveHarness,
  validateHarness,
} from '../lib/api';
import {
  defaultHarnessContent,
  filesForHarnessTab,
  hasUnsafeHarnessPath,
  inferHarnessFileKind,
  nextHarnessPath,
  normalizeHarnessFiles,
} from '../lib/harnessSchema';
import type {
  HarnessBundle,
  HarnessConflictPayload,
  HarnessFile,
  HarnessValidationResult,
  TaskBoardEventRequest,
  TaskBoardResponse,
} from '../lib/types';

type HarnessTab = 'rules' | 'skills' | 'checks' | 'baselines' | 'task-board';

const LAST_PROJECT_KEY = 'ai-team.lastProjectId';
const TABS: Array<{ key: HarnessTab; label: string }> = [
  { key: 'rules', label: 'Rules' },
  { key: 'skills', label: 'Skills' },
  { key: 'checks', label: 'Checks' },
  { key: 'baselines', label: 'Baselines' },
  { key: 'task-board', label: 'Task Board' },
];

function filePayload(files: HarnessFile[]): HarnessFile[] {
  return files.map((file) => ({ path: file.path, content: file.content }));
}

function fileSignature(files: HarnessFile[]): string {
  return JSON.stringify(filePayload(files).sort((a, b) => a.path.localeCompare(b.path)));
}

function canView(bundle: HarnessBundle | null): boolean {
  if (!bundle) return false;
  return bundle.permissions?.can_view !== false;
}

function canEdit(bundle: HarnessBundle | null): boolean {
  return canView(bundle) && bundle?.permissions?.can_edit !== false;
}

function canRunChecks(bundle: HarnessBundle | null): boolean {
  return canEdit(bundle) && bundle?.permissions?.can_run_checks !== false;
}

export function Harness() {
  const [projectId, setProjectId] = useState(() => localStorage.getItem(LAST_PROJECT_KEY) || '');
  const [activeTab, setActiveTab] = useState<HarnessTab>('rules');
  const [bundle, setBundle] = useState<HarnessBundle | null>(null);
  const [drafts, setDrafts] = useState<HarnessFile[]>([]);
  const [loadedSignature, setLoadedSignature] = useState('');
  const [validation, setValidation] = useState<HarnessValidationResult | null>(null);
  const [taskBoard, setTaskBoard] = useState<TaskBoardResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [runningChecks, setRunningChecks] = useState(false);
  const [error, setError] = useState('');
  const [saveMessage, setSaveMessage] = useState('');
  const [conflict, setConflict] = useState<HarnessConflictPayload | null>(null);

  const viewable = canView(bundle);
  const editable = canEdit(bundle);
  const checksRunnable = canRunChecks(bundle);
  const dirty = loadedSignature !== fileSignature(drafts);
  const permissionDenied = bundle?.permissions?.can_view === false;
  const accessMessage = permissionDenied ? '没有权限访问该项目 Harness' : error;
  const noAccess = permissionDenied || error.includes('没有权限') || error.includes('403');

  const loadHarness = useCallback(async (id: string) => {
    if (!id) return;
    setLoading(true);
    setError('');
    setSaveMessage('');
    setValidation(null);
    try {
      const next = await fetchHarness(id);
      const files = normalizeHarnessFiles(next.files || []);
      setBundle({ ...next, files });
      setDrafts(files);
      setLoadedSignature(fileSignature(files));
      setValidation(next.validation || null);
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载 Harness 失败';
      setBundle(null);
      setDrafts([]);
      setLoadedSignature('');
      setError(err instanceof ApiError && err.status === 403 ? '没有权限访问该项目 Harness' : message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadTaskBoard = useCallback(async (id: string) => {
    if (!id) return;
    try {
      setTaskBoard(await fetchTaskBoard(id));
    } catch {
      setTaskBoard(null);
    }
  }, []);

  useEffect(() => {
    if (!projectId) return;
    localStorage.setItem(LAST_PROJECT_KEY, projectId);
    loadHarness(projectId);
    loadTaskBoard(projectId);
  }, [projectId, loadHarness, loadTaskBoard]);

  const tabFiles = useMemo(() => {
    if (activeTab === 'task-board') return [];
    return filesForHarnessTab(drafts, activeTab);
  }, [activeTab, drafts]);

  function updateDraft(path: string, content: string) {
    setDrafts((current) => current.map((file) => file.path === path ? { ...file, content } : file));
    setSaveMessage('');
  }

  function addDraft(tab: Exclude<HarnessTab, 'task-board'>) {
    const path = nextHarnessPath(drafts, tab);
    setDrafts((current) => normalizeHarnessFiles([
      ...current,
      { path, content: defaultHarnessContent(tab), kind: inferHarnessFileKind(path) },
    ]));
    setActiveTab(tab);
  }

  async function handleSave() {
    if (!projectId || !bundle) return;
    setSaving(true);
    setError('');
    setSaveMessage('');
    setConflict(null);
    try {
      if (hasUnsafeHarnessPath(drafts)) {
        setValidation({ valid: false, errors: ['UI drafts contain non-Harness paths'] });
        return;
      }
      const payload = filePayload(drafts);
      const result = await validateHarness(projectId, payload);
      setValidation(result);
      if (!result.valid) return;
      const saved = await saveHarness(projectId, payload, bundle.manifest_hash);
      const files = normalizeHarnessFiles(saved.files || []);
      setBundle({ ...saved, files });
      setDrafts(files);
      setLoadedSignature(fileSignature(files));
      setValidation(saved.validation || result);
      setSaveMessage('Harness 已保存');
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.body && typeof err.body === 'object') {
        setConflict(err.body as HarnessConflictPayload);
        return;
      }
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  async function handleRunChecks() {
    if (!projectId) return;
    setRunningChecks(true);
    setError('');
    try {
      await runHarnessChecks(projectId);
      setSaveMessage('Harness checks 已完成');
    } catch (err) {
      setError(err instanceof Error ? err.message : '运行 checks 失败');
    } finally {
      setRunningChecks(false);
    }
  }

  async function appendEvent(event: TaskBoardEventRequest) {
    if (!projectId) return;
    await appendTaskBoardEvent(projectId, event);
    await loadTaskBoard(projectId);
  }

  const tabTitle = TABS.find((tab) => tab.key === activeTab)?.label || 'Harness';

  return (
    <div className="page harnessPage">
      <header className="pageHeader">
        <div>
          <h1><ShieldCheck size={20} /> Harness</h1>
          <div className="eyebrow">project_id scoped governance</div>
        </div>
        <div className="pageActions">
          {bundle && activeTab !== 'task-board' && editable ? (
            <button className="button primary" onClick={handleSave} disabled={saving || !dirty}>
              <Save size={14} /> {saving ? '保存中' : '保存'}
            </button>
          ) : null}
          {bundle && checksRunnable ? (
            <button className="button" onClick={handleRunChecks} disabled={runningChecks}>
              <Play size={14} /> {runningChecks ? '运行中' : 'Run Checks'}
            </button>
          ) : null}
          {projectId ? (
            <button className="button" onClick={() => { loadHarness(projectId); loadTaskBoard(projectId); }}>
              <RefreshCw size={14} /> 刷新
            </button>
          ) : null}
        </div>
      </header>

      <section className="panel harnessProjectPanel">
        <label htmlFor="harness-project">项目</label>
        <ProjectSelector id="harness-project" value={projectId} onChange={setProjectId} />
        {bundle ? (
          <div className="harnessManifestLine">
            <span className="mono">{bundle.manifest_hash}</span>
            {dirty ? <span className="metaTag metaTagWarning">dirty</span> : null}
          </div>
        ) : null}
      </section>

      {saveMessage ? <div className="saveBanner">{saveMessage}</div> : null}
      {accessMessage ? (
        <div className={noAccess ? 'errorPanel' : 'formError'}>
          {noAccess ? <h2><AlertTriangle size={18} /> 无访问权限</h2> : null}
          <p>{accessMessage}</p>
        </div>
      ) : null}

      {!projectId ? (
        <div className="emptyState">
          <p>请选择项目</p>
        </div>
      ) : loading ? (
        <section className="panel">
          <div className="skeletonLine w-full" />
        </section>
      ) : bundle && viewable && !noAccess ? (
        <>
          <nav className="harnessTabs" aria-label="Harness tabs">
            {TABS.map((tab) => (
              <button key={tab.key} className={activeTab === tab.key ? 'active' : ''} onClick={() => setActiveTab(tab.key)}>
                {tab.label}
              </button>
            ))}
          </nav>

          {validation && validation.errors.length > 0 ? (
            <div className="formError">
              {validation.errors.map((item) => <div key={item}>{item}</div>)}
            </div>
          ) : null}

          {activeTab === 'task-board' ? (
            <HarnessTaskBoard board={taskBoard} canEdit={editable} onAppendEvent={appendEvent} />
          ) : (
            <HarnessAssetEditor
              title={tabTitle}
              files={tabFiles}
              canEdit={editable}
              onChange={updateDraft}
              onAdd={editable ? () => addDraft(activeTab) : undefined}
            />
          )}
        </>
      ) : null}

      {conflict ? (
        <HarnessConflictDialog
          conflict={conflict}
          onClose={() => setConflict(null)}
          onRefresh={() => {
            setConflict(null);
            if (projectId) loadHarness(projectId);
          }}
        />
      ) : null}
    </div>
  );
}
