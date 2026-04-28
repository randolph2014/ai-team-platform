import { KeyRound, Loader2 } from 'lucide-react';
import { useState } from 'react';
import { login } from '../lib/api';

export function Login() {
  const [apiKey, setApiKey] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!apiKey.trim()) return;
    setLoading(true);
    setError('');
    try {
      await login(apiKey.trim());
      window.location.href = '/';
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '登录失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="loginPage">
      <div className="loginCard">
        <div className="brand" style={{ borderBottom: 'none', marginBottom: 8 }}>
          <div className="brandIcon">AI</div>
          <span>AI Team Platform</span>
        </div>
        <form onSubmit={handleSubmit}>
          <h1 style={{ textAlign: 'center' }}>登录</h1>
          <p className="loginHint">请输入 API Key 以继续使用</p>
          {error && <div className="formError">{error}</div>}
          <label>API Key</label>
          <div className="inputWithIcon">
            <KeyRound size={16} />
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              autoFocus
              disabled={loading}
            />
          </div>
          <button className="button primary loginButton" type="submit" disabled={!apiKey.trim() || loading}>
            {loading ? <Loader2 size={16} className="spinner" /> : '登录'}
          </button>
        </form>
      </div>
    </div>
  );
}
