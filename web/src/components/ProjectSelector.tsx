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

export function ProjectSelector({ id, value, onChange, error }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    apiFetch('/projects')
      .then((res) => {
        if (!res.ok) return [];
        return res.json();
      })
      .then((data: Project[]) => setProjects(data))
      .catch(() => setProjects([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <>
        <select id={id} disabled>
          <option>加载中...</option>
        </select>
      </>
    );
  }

  if (projects.length === 0) {
    return (
      <>
        <select id={id} disabled>
          <option>无可用项目</option>
        </select>
        <span className="fieldError">请先在 /api/projects 创建项目</span>
      </>
    );
  }

  return (
    <>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">选择项目</option>
        {projects.map((p) => (
          <option key={p.id} value={p.id}>{p.name} ({p.root_path})</option>
        ))}
      </select>
      {error && <span className="fieldError">{error}</span>}
    </>
  );
}
