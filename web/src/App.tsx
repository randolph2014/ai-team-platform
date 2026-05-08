import { Activity, Boxes, CircleDollarSign, History, LogOut, Settings2, Webhook } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Navigate, NavLink, Outlet, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { checkAuthStatus, clearToken, isLoggedIn } from './lib/api';
import { ErrorBoundary } from './components/ErrorBoundary';
import { NewRunModal } from './components/NewRunModal';
import { Costs } from './pages/Costs';
import { Dashboard } from './pages/Dashboard';
import { Login } from './pages/Login';
import { PipelineEditor } from './pages/PipelineEditor';
import { Pipelines } from './pages/Pipelines';
import { RunDetail } from './pages/RunDetail';
import { Runs } from './pages/Runs';
import { Settings } from './pages/Settings';
import { Webhooks } from './pages/Webhooks';

function RunDetailRoute() {
  const { runId } = useParams();
  return <RunDetail runId={runId || ''} />;
}

function PipelineEditorRoute() {
  const { pipelineId } = useParams();
  return <PipelineEditor pipelineId={pipelineId} />;
}

function AuthGate({ children }: { children: React.ReactNode }) {
  const [authChecked, setAuthChecked] = useState(false);
  const [authEnabled, setAuthEnabled] = useState(true);

  useEffect(() => {
    checkAuthStatus().then((enabled) => {
      setAuthEnabled(enabled);
      setAuthChecked(true);
    });
  }, []);

  if (!authChecked) return null;
  if (authEnabled && !isLoggedIn()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function AppLayout() {
  const navigate = useNavigate();
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  useEffect(() => {
    const onAuthExpired = () => {
      navigateRef.current('/login', { replace: true });
    };
    window.addEventListener('auth:expired', onAuthExpired);
    return () => window.removeEventListener('auth:expired', onAuthExpired);
  }, []);

  const [modalOpen, setModalOpen] = useState(false);

  const nav = [
    ['/dashboard', Activity, '仪表盘'],
    ['/runs', History, '执行记录'],
    ['/pipelines', Boxes, 'Pipeline 模板'],
    ['/webhooks', Webhook, 'Webhook'],
    ['/costs', CircleDollarSign, '成本追踪'],
    ['/settings', Settings2, '设置'],
  ] as const;

  function handleLogout() {
    clearToken();
    navigate('/login', { replace: true });
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><div className="brandIcon">AI</div><span>AI Team Platform</span></div>
        <nav>
          <div className="navSection">概览</div>
          {nav.slice(0, 2).map(([path, Icon, label]) => (
            <NavLink key={path} to={path} className={({ isActive }) => isActive ? 'active' : ''}>
              <Icon size={17} /> <span>{label}</span>
            </NavLink>
          ))}
          <div className="navSection">配置</div>
          {nav.slice(2).map(([path, Icon, label]) => (
            <NavLink key={path} to={path} className={({ isActive }) => isActive ? 'active' : ''}>
              <Icon size={17} /> <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <footer>
          <button className="logoutButton" onClick={handleLogout}>
            <LogOut size={16} /> <span>退出登录</span>
          </button>
        </footer>
      </aside>
      <main>
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
      <NewRunModal open={modalOpen} onClose={() => setModalOpen(false)} onRefreshNeeded={() => {}} />
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/*"
        element={
          <AuthGate>
            <AppLayout />
          </AuthGate>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard onNewRun={() => {}} />} />
        <Route path="runs" element={<Runs onNewRun={() => {}} />} />
        <Route path="runs/:runId" element={<RunDetailRoute />} />
        <Route path="pipelines" element={<Pipelines />} />
        <Route path="pipelines/editor" element={<PipelineEditorRoute />} />
        <Route path="pipelines/editor/:pipelineId" element={<PipelineEditorRoute />} />
        <Route path="webhooks" element={<Webhooks />} />
        <Route path="costs" element={<Costs />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
