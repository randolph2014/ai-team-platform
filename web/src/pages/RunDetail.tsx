import { Archive, CheckCircle, Clock, Eye, FileDiff, FileText, FolderGit2, GitBranchPlus, RefreshCw, Wifi, WifiOff, X, XCircle } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { ArtifactViewer } from '../components/ArtifactViewer';
import { HarnessReportPanel } from '../components/HarnessReportPanel';
import { PipelineTimeline } from '../components/PipelineTimeline';
import { StatusBadge } from '../components/StatusBadge';
import { apiFetch, fetchRun, fetchRunArtifactText, fetchRunDiff, projectQuery, rememberedWorkdir, rememberRunWorkdir, runWebSocketUrl } from '../lib/api';
import { parseHarnessReport } from '../lib/harnessSchema';
import type { HarnessReport, RunEvent, RunReport, StageRun } from '../lib/types';

function artifactColor(name: string): string {
  if (/\.(md|markdown)$/i.test(name)) return 'var(--blue)';
  if (/\.json$/i.test(name)) return 'var(--yellow)';
  if (/\.(py|js|ts|tsx|jsx)$/i.test(name)) return 'var(--green)';
  if (/\.(log|out|err)$/i.test(name)) return 'var(--text-muted)';
  if (/\.(yaml|yml)$/i.test(name)) return 'var(--purple)';
  return 'var(--accent)';
}

function fileIcon(file: string): string {
  if (/\.(py|js|ts|tsx|jsx|go|rs|java|kt|swift)$/i.test(file)) return 'var(--green)';
  if (/\.(yaml|yml|json|toml)$/i.test(file)) return 'var(--yellow)';
  if (/\.(md|markdown|rst|txt)$/i.test(file)) return 'var(--blue)';
  if (/\.(css|scss|less)$/i.test(file)) return 'var(--purple)';
  return 'var(--text-secondary)';
}

const KEY_MILESTONES = [
  {
    stageId: 'requirement_confirm',
    label: '需求定稿确认',
    description: '需求定稿后由人工确认是否进入规划',
  },
  {
    stageId: 'task_plan_confirm',
    label: '任务规划确认',
    description: '任务拆分完成后由人工确认实施范围',
  },
  {
    stageId: 'acceptance_confirm',
    label: '最终交付确认',
    description: '交付前由人工确认验收结果',
  },
  {
    stageId: 'retrospect',
    label: '需求总结报告',
    description: '交付后沉淀总结、产物和后续建议',
  },
] as const;

function milestoneStage(run: RunReport, stageId: string): StageRun | null {
  return run.stages.find((stage) => stage.stage_id === stageId) || null;
}

function milestoneArtifact(run: RunReport, stageId: string): string | null {
  if (stageId === 'retrospect') {
    return run.artifacts.find((artifact) => /^retrospect-report\.(md|json)$/i.test(artifact)) || null;
  }
  return null;
}

function KeyMilestones({ run }: { run: RunReport }) {
  return (
    <section className="panel milestonePanel">
      <div className="panelHeader">
        <h2><CheckCircle size={16} /> 关键节点</h2>
      </div>
      <div className="milestoneGrid">
        {KEY_MILESTONES.map((milestone) => {
          const stage = milestoneStage(run, milestone.stageId);
          const artifact = milestoneArtifact(run, milestone.stageId);
          const resolvedStatus = stage?.status || (artifact ? 'completed' : null);
          return (
            <div className={`milestoneItem ${resolvedStatus ? '' : 'milestoneItemMissing'}`} key={milestone.stageId}>
              <div className="milestoneMain">
                <div className="milestoneTitle">{milestone.label}</div>
                <div className="milestoneDescription">{milestone.description}</div>
                {artifact ? <div className="milestoneArtifact mono">{artifact}</div> : null}
                {stage?.human_decision ? (
                  <div className="milestoneDecision">
                    决策：{stage.human_decision.decision === 'approved' ? '已通过' : stage.human_decision.decision === 'rejected' ? '已拒绝' : '待确认'}
                  </div>
                ) : null}
              </div>
              {resolvedStatus ? <StatusBadge status={resolvedStatus} /> : <span className="milestoneMissing">未配置</span>}
            </div>
          );
        })}
      </div>
    </section>
  );
}

export function RunDetail({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunReport | null>(null);
  const [projectId, setProjectId] = useState('');
  const [harnessReport, setHarnessReport] = useState<HarnessReport | null>(null);
  const [liveLines, setLiveLines] = useState<string[]>([]);
  const [workdir, setWorkdir] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [wsConnected, setWsConnected] = useState(false);
  const [viewingArtifact, setViewingArtifact] = useState<string | null>(null);
  const [changedFiles, setChangedFiles] = useState<string[]>([]);
  const [diffStat, setDiffStat] = useState('');
  const [viewingDiff, setViewingDiff] = useState(false);
  const [diffContent, setDiffContent] = useState('');
  const [diffLoading, setDiffLoading] = useState(false);
  const terminalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const queryWorkdir = new URLSearchParams(window.location.search).get('workdir') || '';
    const queryProjectId = new URLSearchParams(window.location.search).get('project_id') || '';
    setProjectId(queryProjectId);
    const resolvedWorkdir = queryProjectId ? '' : (queryWorkdir || rememberedWorkdir(runId));
    setWorkdir(resolvedWorkdir);
    let ignore = false;
    setLoadError(null);
    setLoading(true);
    setRun(null);
    fetchRun(runId, queryProjectId ? { projectId: queryProjectId } : resolvedWorkdir)
      .then((payload) => {
        if (ignore) return;
        setRun(payload);
        setWorkdir(payload.project_root || resolvedWorkdir);
        rememberRunWorkdir(runId, payload.project_root);
        setChangedFiles(payload.changed_files || []);
        setDiffStat(payload.diff_stat || '');
      })
      .catch((error: Error) => {
        if (!ignore) setLoadError(error.message);
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => { ignore = true; };
  }, [runId]);

  useEffect(() => {
    if (!run || !workdir) return;
    let disposed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectDelay = 1000;
    const MAX_RECONNECT_DELAY = 30000;

    function connect() {
      if (disposed) return;
      const socket = new WebSocket(runWebSocketUrl(runId));
      socket.onopen = () => {
        if (!disposed) {
          setWsConnected(true);
          reconnectDelay = 1000;
        }
      };
      socket.onclose = () => {
        if (!disposed) {
          setWsConnected(false);
          reconnectTimer = setTimeout(() => {
            reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
            connect();
          }, reconnectDelay);
        }
      };
      socket.onerror = () => {
        if (!disposed) setWsConnected(false);
      };
      socket.onmessage = (message) => {
        const event = JSON.parse(message.data) as RunEvent;
        if (event.type === 'agent:output' && typeof event.payload.text === 'string') {
          setLiveLines((lines) => [...lines.slice(-120), event.payload.text as string]);
        }
        if (event.type === 'run:completed') {
          fetchRun(runId, projectId ? { projectId } : workdir).then((updated) => {
            if (!disposed) {
              setRun(updated);
              setChangedFiles(updated.changed_files || []);
              setDiffStat(updated.diff_stat || '');
            }
          }).catch(() => undefined);
        }
        if (event.type === 'files:changed') {
          const files = (event.payload.changed_files as string[]) || [];
          if (files.length) setChangedFiles(files);
          if (typeof event.payload.diff_stat === 'string') setDiffStat(event.payload.diff_stat);
        }
      };
    }

    connect();
    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [run ? run.run_id : '', workdir, projectId]);

  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [liveLines]);

  useEffect(() => {
    if (!run || !run.artifacts.some((artifact) => artifact === 'harness-report.json')) {
      setHarnessReport(null);
      return;
    }
    let ignore = false;
    fetchRunArtifactText(run.run_id, 'harness-report.json', projectId ? { projectId } : (workdir || run.project_root))
      .then((content) => {
        if (ignore) return;
        setHarnessReport(parseHarnessReport(content));
      })
      .catch(() => {
        if (!ignore) setHarnessReport(null);
      });
    return () => { ignore = true; };
  }, [run ? run.run_id : '', run ? run.artifacts.join('|') : '', projectId, workdir]);

  async function handleViewDiff() {
    setDiffLoading(true);
    setViewingDiff(true);
    try {
      const result = await fetchRunDiff(runId, projectId ? { projectId } : workdir);
      setDiffContent(result.diff);
    } catch {
      setDiffContent(diffStat || '暂无 diff 数据');
    } finally {
      setDiffLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="page">
        <section className="runHeader skeleton">
          <div>
            <div className="eyebrow skeletonLine w-120" />
            <div className="skeletonLine w-180" style={{ height: 24 }} />
            <div className="runMeta" style={{ marginTop: 10 }}>
              <div className="skeletonLine w-80" />
              <div className="skeletonLine w-200" />
              <div className="skeletonLine w-140" />
            </div>
          </div>
        </section>
        <section className="panel requirementPanel">
          <div className="skeletonLine w-80" style={{ marginBottom: 8 }} />
          <div className="skeletonLine w-full" />
        </section>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="page">
        <div className="errorPanel">
          <h2>加载失败</h2>
          <p>{loadError}</p>
          <button className="button primary" onClick={() => {
            setLoadError(null);
            setLoading(true);
            fetchRun(runId, projectId ? { projectId } : workdir)
              .then(setRun)
              .catch((error: Error) => setLoadError(error.message))
              .finally(() => setLoading(false));
          }}>重试</button>
        </div>
      </div>
    );
  }

  if (!run) return null;

  async function handleRunAction(action: 'cancel' | 'retry' | 'archive') {
    const wd = workdir || run!.project_root;
    const qs = projectId ? projectQuery({ projectId }) : (wd ? `?workdir=${encodeURIComponent(wd)}` : '');
    const res = await apiFetch(`/runs/${runId}/${action}${qs}`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '操作失败' }));
      throw new Error(err.detail || `操作失败: ${res.status}`);
    }
    const updated = await fetchRun(runId, projectId ? { projectId } : wd);
    setRun(updated);
  }

  const canCancel = ['queued', 'running', 'paused', 'resuming', 'blocked'].includes(run.status);
  const canRetry = run.status === 'failed' || run.status === 'blocked';
  const canArchive = ['completed', 'failed', 'cancelled', 'blocked'].includes(run.status);
  const hasDiffData = changedFiles.length > 0 || Boolean(diffStat.trim());
  const diffSummary = diffStat.trim().split('\n').filter(Boolean).slice(-1)[0] || '本次运行没有检测到代码变更';

  return (
    <div className="page">
      <section className="runHeader">
        <div>
          <div className="eyebrow">Pipeline: {run.config_source || 'Standard'}</div>
          <h1>Run #{run.run_id}</h1>
          <div className="runMeta">
            <StatusBadge status={run.status} />
            <span><FolderGit2 size={14} /> {run.project_root}</span>
            <span>{run.started_at ? new Date(run.started_at).toLocaleString('zh-CN') : '-'}</span>
            <span className={wsConnected ? 'wsIndicator wsConnected' : 'wsIndicator wsDisconnected'}>
              {wsConnected ? <Wifi size={13} /> : <WifiOff size={13} />}
              {wsConnected ? '实时连接' : '已断开'}
            </span>
          </div>
        </div>
      </section>

      <section className="panel requirementPanel">
        <h2>需求描述</h2>
        <p>{run.requirement}</p>
        {loadError ? <p className="inlineError">无法加载真实运行记录：{loadError}</p> : null}
      </section>

      {harnessReport ? <HarnessReportPanel report={harnessReport} /> : null}
      <KeyMilestones run={run} />

      {(canCancel || canRetry || canArchive) && (
        <section className="panel runActionsPanel">
          <div className="runActionsButtons">
            {canCancel && (
              <button className="button" onClick={() => handleRunAction('cancel')}>
                <XCircle size={14} /> 取消
              </button>
            )}
            {canRetry && (
              <button className="button" onClick={() => handleRunAction('retry')}>
                <RefreshCw size={14} /> 重试
              </button>
            )}
            {canArchive && (
              <button
                className="button"
                onClick={() => handleRunAction('archive')}
                title="将运行状态标记为已归档，保留运行记录和产物"
                aria-label="移入归档：保留运行记录和产物"
              >
                <Archive size={14} /> 移入归档
              </button>
            )}
          </div>
        </section>
      )}

      {run.error_detail && (run.error_detail.error_type || run.error_detail.error_message || run.error_detail.traceback) && (
        <section className="panel errorDetailPanel">
          <h2><XCircle size={16} /> 错误详情</h2>
          {run.error_detail.error_type && (
            <div className="errorDetailRow">
              <span className="errorDetailLabel">类型</span>
              <span className="errorDetailValue mono">{run.error_detail.error_type}</span>
            </div>
          )}
          {run.error_detail.error_message && (
            <div className="errorDetailRow">
              <span className="errorDetailLabel">信息</span>
              <span className="errorDetailValue">{run.error_detail.error_message}</span>
            </div>
          )}
          {run.error_detail.traceback && (
            <details>
              <summary>调用栈</summary>
              <pre className="errorTraceback">{run.error_detail.traceback}</pre>
            </details>
          )}
        </section>
      )}

      {run.status_timeline && run.status_timeline.length > 0 && (
        <section className="panel statusTimelinePanel">
          <h2><Clock size={16} /> 状态时间线</h2>
          <div className="statusTimeline">
            {run.status_timeline.map((entry, idx) => (
              <div key={idx} className="statusTimelineEntry">
                <span className="statusTimelineDot" />
                <div className="statusTimelineContent">
                  <StatusBadge status={entry.status} />
                  <span className="statusTimelineTime">
                    {new Date(entry.timestamp).toLocaleString('zh-CN')}
                  </span>
                  {entry.reason && <span className="statusTimelineReason">{entry.reason}</span>}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="panel fileChangesPanel">
        <div className="panelHeader">
          <h2><GitBranchPlus size={16} /> 代码变更<span className="artifactCount">{changedFiles.length}</span></h2>
          <button className="button" onClick={handleViewDiff} disabled={!hasDiffData}>
            <FileDiff size={14} /> 查看 Diff
          </button>
        </div>
        <div className="fileChangesSummary">
          <div>
            <span className="summaryLabel">文件数</span>
            <strong>{changedFiles.length}</strong>
          </div>
          <div>
            <span className="summaryLabel">统计</span>
            <strong>{diffSummary}</strong>
          </div>
        </div>
        {changedFiles.length > 0 ? (
          <div className="fileChangesList">
            {changedFiles.map((file) => (
              <div key={file} className="fileChangeItem">
                <span className="fileChangeDot" style={{ background: fileIcon(file) }} />
                <span className="fileChangeName mono">{file}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="fileChangesEmpty">暂无代码文件变更</div>
        )}
        {diffStat && (
          <div className="fileChangesStat">
            <FileText size={12} />
            <span>{diffStat.split('\n').slice(0, 2).join(' | ')}</span>
          </div>
        )}
      </section>

      <div className="detailGrid">
        <PipelineTimeline
          run={run}
          liveLines={liveLines}
          projectId={projectId || undefined}
          onStageAction={() => {
            fetchRun(runId, projectId ? { projectId } : (workdir || run.project_root))
              .then(setRun)
              .catch(() => undefined);
          }}
        />
        <aside className="artifactPanel">
          <h2>产物文件 <span className="artifactCount">{run.artifacts.length}</span></h2>
          {run.artifacts.length === 0 ? (
            <div className="artifactEmpty">暂无产物文件</div>
          ) : (
            <div className="artifactList">
              {run.artifacts.map((artifact) => (
                <button
                  key={artifact}
                  className="artifactItem"
                  onClick={() => setViewingArtifact(artifact)}
                  title={`点击查看 ${artifact}`}
                >
                  <span className="artifactDot" style={{ background: artifactColor(artifact) }} />
                  <span className="artifactName">{artifact}</span>
                  <Eye size={12} className="artifactViewIcon" />
                </button>
              ))}
            </div>
          )}
        </aside>
      </div>

      {viewingArtifact && (
        <ArtifactViewer
          runId={run.run_id}
          artifactName={viewingArtifact}
          projectId={projectId || undefined}
          onClose={() => setViewingArtifact(null)}
        />
      )}

      {viewingDiff && (
        <div className="modalOverlay" onClick={() => setViewingDiff(false)}>
          <div className="modal modalWide" onClick={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <h2><FileDiff size={18} /> Git Diff</h2>
              <button className="iconButton" onClick={() => setViewingDiff(false)} aria-label="关闭">
                <X size={16} />
              </button>
            </div>
            <div className="diffContent">
              {diffLoading ? (
                <div className="emptyState" style={{ padding: 32 }}>
                  <span className="spinner" style={{ display: 'inline-block', width: 24, height: 24, border: '2px solid var(--border)', borderTopColor: 'var(--accent)', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                  <span style={{ marginTop: 12 }}>加载 diff...</span>
                </div>
              ) : (
                <pre className="diffPre">{diffContent || '暂无 diff 数据'}</pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
