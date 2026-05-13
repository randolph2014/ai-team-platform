import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';

export interface Project {
  id: string;
  name: string;
  root_path: string;
  created_at?: string;
}

interface Props {
  id?: string;
  value: string;
  onChange: (projectId: string) => void;
  error?: string;
}

interface DirectoryEntry {
  name: string;
  path: string;
}

interface DirectoryBrowseResponse {
  path: string | null;
  parent: string | null;
  entries: DirectoryEntry[];
}

function projectOptionLabel(project: Project): string {
  return `${project.name} (${project.root_path})`;
}

export function ProjectSelector({ id, value, onChange, error }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseError, setBrowseError] = useState('');
  const [browsePath, setBrowsePath] = useState<string | null>(null);
  const [browseParent, setBrowseParent] = useState<string | null>(null);
  const [entries, setEntries] = useState<DirectoryEntry[]>([]);
  const [importing, setImporting] = useState(false);

  function loadProjects() {
    setLoading(true);
    apiFetch('/projects')
      .then((res) => {
        if (!res.ok) return [];
        return res.json();
      })
      .then((data: Project[]) => setProjects(data))
      .catch(() => setProjects([]))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadProjects();
  }, []);

  function loadDirectory(path?: string | null) {
    setBrowseLoading(true);
    setBrowseError('');
    const query = path ? `?path=${encodeURIComponent(path)}` : '';
    apiFetch(`/projects/browse${query}`)
      .then((res) => {
        if (!res.ok) throw new Error(`读取目录失败: ${res.status}`);
        return res.json();
      })
      .then((data: DirectoryBrowseResponse) => {
        setBrowsePath(data.path);
        setBrowseParent(data.parent);
        setEntries(data.entries || []);
      })
      .catch((err: Error) => setBrowseError(err.message || '读取目录失败'))
      .finally(() => setBrowseLoading(false));
  }

  function openPicker() {
    setPickerOpen(true);
    loadDirectory(null);
  }

  async function importSelectedPath() {
    if (!browsePath) return;
    setImporting(true);
    setBrowseError('');
    try {
      const response = await apiFetch('/projects/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root_path: browsePath }),
      });
      if (!response.ok) throw new Error(`引入项目失败: ${response.status}`);
      const project = await response.json() as Project;
      setProjects((prev) => {
        const withoutDuplicate = prev.filter((item) => item.id !== project.id);
        return [...withoutDuplicate, project].sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'));
      });
      onChange(project.id);
      setPickerOpen(false);
    } catch (err) {
      setBrowseError(err instanceof Error ? err.message : '引入项目失败');
    } finally {
      setImporting(false);
    }
  }

  return (
    <>
      <div className="projectPathControl">
        <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={loading}>
          <option value="">{loading ? '加载中...' : '选择项目路径'}</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{projectOptionLabel(p)}</option>
          ))}
        </select>
        <button type="button" className="button" onClick={openPicker}>选择项目路径</button>
      </div>
      {error && <span className="fieldError">{error}</span>}
      {pickerOpen && (
        <div className="projectPicker" role="dialog" aria-modal="true">
          <div className="projectPickerHeader">
            <h3>选择项目路径</h3>
            <button type="button" className="iconButton" onClick={() => setPickerOpen(false)} aria-label="关闭路径选择">×</button>
          </div>
          {browseError && <div className="formError">{browseError}</div>}
          <div className="projectPickerCurrent">{browsePath || '可用根目录'}</div>
          <div className="projectPickerList">
            {browseParent && (
              <button type="button" className="projectPickerRow" onClick={() => loadDirectory(browseParent)}>
                ..
              </button>
            )}
            {browseLoading ? (
              <div className="projectPickerEmpty">加载中...</div>
            ) : entries.length === 0 ? (
              <div className="projectPickerEmpty">没有可继续展开的目录</div>
            ) : (
              entries.map((entry) => (
                <button key={entry.path} type="button" className="projectPickerRow" onClick={() => loadDirectory(entry.path)}>
                  {entry.name}
                </button>
              ))
            )}
          </div>
          <div className="projectPickerActions">
            <button type="button" className="button" onClick={() => setPickerOpen(false)}>取消</button>
            <button type="button" className="button primary" disabled={!browsePath || importing} onClick={importSelectedPath}>
              {importing ? '引入中...' : '引入并选择'}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
