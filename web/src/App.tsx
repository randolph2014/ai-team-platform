import { Activity, Boxes, Gauge, History, Settings2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { NewRunModal } from './components/NewRunModal';
import { Dashboard } from './pages/Dashboard';
import { Pipelines } from './pages/Pipelines';
import { RunDetail } from './pages/RunDetail';
import { Runs } from './pages/Runs';
import { Settings } from './pages/Settings';

type Route = 'dashboard' | 'runs' | 'run-detail' | 'pipelines' | 'settings';

function currentRoute(): { route: Route; runId?: string } {
  const path = window.location.pathname;
  if (path.startsWith('/runs/')) return { route: 'run-detail', runId: path.split('/')[2] };
  if (path === '/runs') return { route: 'runs' };
  if (path === '/pipelines') return { route: 'pipelines' };
  if (path === '/settings') return { route: 'settings' };
  return { route: 'dashboard' };
}

function navigate(path: string) {
  window.history.pushState({}, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export function App() {
  const [route, setRoute] = useState(currentRoute());
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    const listener = () => setRoute(currentRoute());
    window.addEventListener('popstate', listener);
    return () => window.removeEventListener('popstate', listener);
  }, []);

  const nav = [
    ['dashboard', '/dashboard', Activity, '仪表盘'],
    ['runs', '/runs', History, '执行记录'],
    ['pipelines', '/pipelines', Boxes, 'Pipeline 模板'],
    ['settings', '/settings', Settings2, '设置'],
  ] as const;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><div className="brandIcon">AI</div><span>AI Team Platform</span></div>
        <nav>
          <div className="navSection">概览</div>
          {nav.slice(0, 2).map(([key, path, Icon, label]) => (
            <button key={key} className={route.route === key ? 'active' : ''} onClick={() => navigate(path)}>
              <Icon size={17} /> <span>{label}</span>
            </button>
          ))}
          <div className="navSection">配置</div>
          {nav.slice(2).map(([key, path, Icon, label]) => (
            <button key={key} className={route.route === key ? 'active' : ''} onClick={() => navigate(path)}>
              <Icon size={17} /> <span>{label}</span>
            </button>
          ))}
        </nav>
        <footer><Gauge size={16} /> filesystem mode</footer>
      </aside>
      <main>
        {route.route === 'dashboard' && <Dashboard onNewRun={() => setModalOpen(true)} />}
        {route.route === 'runs' && <Runs onNewRun={() => setModalOpen(true)} />}
        {route.route === 'run-detail' && <RunDetail runId={route.runId ?? '42'} />}
        {route.route === 'pipelines' && <Pipelines />}
        {route.route === 'settings' && <Settings />}
      </main>
      <NewRunModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </div>
  );
}
