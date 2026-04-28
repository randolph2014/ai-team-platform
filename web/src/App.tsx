import { Activity, Boxes, History, LogOut, PenLine, Settings2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { checkAuthStatus, clearToken, isLoggedIn } from './lib/api';
import { NewRunModal } from './components/NewRunModal';
import { Dashboard } from './pages/Dashboard';
import { Login } from './pages/Login';
import { PipelineEditor } from './pages/PipelineEditor';
import { Pipelines } from './pages/Pipelines';
import { RunDetail } from './pages/RunDetail';
import { Runs } from './pages/Runs';
import { Settings } from './pages/Settings';

type Route = 'dashboard' | 'runs' | 'run-detail' | 'pipelines' | 'pipeline-editor' | 'settings' | 'login';

function currentRoute(): { route: Route; runId?: string; pipelineId?: string } {
  const path = window.location.pathname;
  if (path === '/login') return { route: 'login' };
  if (path.startsWith('/runs/')) return { route: 'run-detail', runId: path.split('/')[2] };
  if (path === '/runs') return { route: 'runs' };
  if (path.startsWith('/pipelines/editor/')) return { route: 'pipeline-editor', pipelineId: path.split('/')[3] };
  if (path === '/pipelines/editor' || path === '/pipeline-editor') return { route: 'pipeline-editor' };
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
  const [authenticated, setAuthenticated] = useState(isLoggedIn());
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    checkAuthStatus().then((enabled) => {
      if (!enabled) {
        setAuthenticated(true);
      }
      setAuthChecked(true);
    });
  }, []);

  useEffect(() => {
    const listener = () => {
      setRoute(currentRoute());
    };
    const authListener = () => {
      setAuthenticated(false);
    };
    window.addEventListener('popstate', listener);
    window.addEventListener('auth:expired', authListener);
    return () => {
      window.removeEventListener('popstate', listener);
      window.removeEventListener('auth:expired', authListener);
    };
  }, []);

  useEffect(() => {
    if (!authenticated && route.route !== 'login') {
      navigate('/login');
    }
    if (authenticated && route.route === 'login') {
      navigate('/dashboard');
    }
  }, [authenticated, route.route]);

  if (!authChecked) {
    return null;
  }

  if (!authenticated) {
    return <Login />;
  }

  const nav = [
    ['dashboard', '/dashboard', Activity, '仪表盘'],
    ['runs', '/runs', History, '执行记录'],
    ['pipelines', '/pipelines', Boxes, 'Pipeline 模板'],
    ['settings', '/settings', Settings2, '设置'],
  ] as const;

  function handleLogout() {
    clearToken();
    setAuthenticated(false);
    navigate('/login');
  }

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
        <footer>
          <button className="logoutButton" onClick={handleLogout}>
            <LogOut size={16} /> 退出登录
          </button>
        </footer>
      </aside>
      <main>
        {route.route === 'dashboard' && <Dashboard onNewRun={() => setModalOpen(true)} />}
        {route.route === 'runs' && <Runs onNewRun={() => setModalOpen(true)} />}
        {route.route === 'run-detail' && <RunDetail runId={route.runId ?? ''} />}
        {route.route === 'pipelines' && <Pipelines />}
        {route.route === 'pipeline-editor' && <PipelineEditor pipelineId={route.pipelineId} />}
        {route.route === 'settings' && <Settings />}
      </main>
      <NewRunModal open={modalOpen} onClose={() => setModalOpen(false)} onRefreshNeeded={() => {}} />
    </div>
  );
}
