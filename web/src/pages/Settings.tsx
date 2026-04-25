import { Bot, CheckCircle2, FolderGit2, Gauge, RadioTower, Settings2 } from 'lucide-react';

const sections = [
  ['Provider', Bot, [['默认 Provider', 'Auto'], ['Claude 参数', '-p --output-format stream-json'], ['Codex 参数', 'exec']]],
  ['Context Scanner', RadioTower, [['启用扫描', 'on'], ['最大文件大小', '50000'], ['排除目录', 'node_modules, .git, build']]],
  ['Worktree', FolderGit2, [['隔离模式', 'per-run'], ['基础分支', 'main'], ['合并策略', 'squash']]],
  ['Quality Gates', CheckCircle2, [['编译门禁', 'required'], ['测试门禁', 'required'], ['覆盖率门禁', 'warning']]],
  ['Runner', Gauge, [['Agent 超时', '1800s'], ['Heartbeat', '60s'], ['并行日志', 'interleaved']]],
];

export function Settings() {
  return (
    <div className="page">
      <header className="pageHeader"><h1>设置</h1></header>
      <div className="settingsGrid">
        <aside className="settingsNav">
          {sections.map(([name, Icon]) => {
            const Component = Icon as typeof Settings2;
            return <a key={name as string}><Component size={14} /> {name as string}</a>;
          })}
        </aside>
        <section className="panel">
          {sections.map(([name, Icon, rows]) => {
            const Component = Icon as typeof Settings2;
            return (
              <div className="settingGroup" key={name as string}>
                <h2><Component size={16} /> {name as string}</h2>
                {(rows as string[][]).map(([label, value]) => (
                  <div className="settingRow" key={label}>
                    <div>
                      <strong>{label}</strong>
                      <small>来自平台默认模板，可被项目 .ai/team.yaml 覆盖</small>
                    </div>
                    <code>{value}</code>
                  </div>
                ))}
              </div>
            );
          })}
        </section>
      </div>
    </div>
  );
}
