import { CheckCircle, Clock, FileText, XCircle } from 'lucide-react';
import { useState } from 'react';
import type { RunReport, StageRun } from '../lib/types';
import { rememberedWorkdir, resumeRun } from '../lib/api';
import { ArtifactContent } from './ArtifactContent';
import { StatusBadge } from './StatusBadge';

function formatTime(iso?: string) {
  if (!iso) return null;
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

function formatDuration(seconds?: number) {
  if (seconds == null) return null;
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m${s}s`;
}

function ReviewActions({ stage, runId, workdir, onActionDone }: {
  stage: StageRun;
  runId: string;
  workdir: string;
  onActionDone: () => void;
}) {
  const [acting, setActing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (stage.type !== 'human_review' || stage.status !== 'waiting') return null;

  function handleApprove() {
    setActing(true);
    setError(null);
    resumeRun(runId, workdir, true, false)
      .then(() => onActionDone())
      .catch((e: Error) => setError(e.message))
      .finally(() => setActing(false));
  }

  function handleReject() {
    setActing(true);
    setError(null);
    resumeRun(runId, workdir, false, true)
      .then(() => onActionDone())
      .catch((e: Error) => setError(e.message))
      .finally(() => setActing(false));
  }

  return (
    <div className="reviewActions">
      <div className="reviewActionsButtons">
        <button
          className="button primary"
          onClick={handleApprove}
          disabled={acting}
        >
          <CheckCircle size={14} /> 通过
        </button>
        <button
          className="button reviewRejectButton"
          onClick={handleReject}
          disabled={acting}
        >
          <XCircle size={14} /> 拒绝
        </button>
      </div>
      {error && <p className="reviewActionError">{error}</p>}
    </div>
  );
}

function StageCard({ stage, liveLines, runId, workdir, onStageAction }: {
  stage: StageRun;
  liveLines: string[];
  runId: string;
  workdir: string;
  onStageAction: () => void;
}) {
  const lines = liveLines;
  const stageStart = formatTime(stage.started_at);
  const stageEnd = formatTime(stage.completed_at);
  const stageDuration = formatDuration(stage.duration_seconds);
  return (
    <section className={`stageCard stage-${stage.status}`}>
      <header className="stageHeader">
        <div className="stageTitle">
          <span className="stageName">{stage.stage_name}</span>
          {stage.is_parallel && <span className="stageTag">parallel</span>}
          {stage.type === 'human_review' && <span className="stageTag">accept</span>}
          {stageDuration && (
            <span className="stageTag stageDuration"><Clock size={11} /> {stageDuration}</span>
          )}
        </div>
        <StatusBadge status={stage.status} />
      </header>
      {(stageStart || stageEnd) && (
        <div className="stageTimeInfo">
          {stageStart && <span className="stageTimeItem">开始 {stageStart}</span>}
          {stageEnd && <span className="stageTimeItem">结束 {stageEnd}</span>}
        </div>
      )}
      {stage.error_message && (
        <div className="stageError">{stage.error_message}</div>
      )}
      <div className="stageBody">
        {stage.agents.map((agent) => {
          const agentStart = formatTime(agent.started_at);
          const agentEnd = formatTime(agent.completed_at);
          return (
          <div className="agentRow" key={`${stage.stage_id}-${agent.agent_name}`}>
            <div className="agentInfo">
              <div className="agentIcon">{agent.agent_name.slice(0, 2).toUpperCase()}</div>
              <div>
                <div className="agentName">{agent.agent_name}</div>
                <div className="agentRole">{agent.role ?? agent.runtime_id ?? agent.runtime_cli}</div>
                {(agentStart || agent.model_used) && (
                  <div className="agentDetail">
                    {agentStart && <span>{agentStart}</span>}
                    {agentEnd && <span> → {agentEnd}</span>}
                    {agent.model_used && <span className="agentModel">{agent.model_used}</span>}
                  </div>
                )}
                {agent.error_message && <div className="agentError">{agent.error_message}</div>}
              </div>
            </div>
            <div className="agentMeta">
              {agent.duration_seconds ? <span>{Math.round(agent.duration_seconds)}s</span> : null}
              {agent.exit_code != null && agent.exit_code !== 0 && <span className="agentExitCode">exit {agent.exit_code}</span>}
              {agent.output_file ? (
                <span className="artifactLink">
                  <FileText size={13} /> {agent.output_file.split('/').pop()}
                </span>
              ) : null}
              <StatusBadge status={agent.status} />
            </div>
          </div>
          );
        })}
        {stage.agents.some((a) => a.output_file) && (
          <div className="stageArtifacts">
            {stage.agents
              .filter((a) => a.output_file)
              .map((agent) => (
                <ArtifactContent
                  key={`${stage.stage_id}-${agent.agent_name}-${agent.output_file}`}
                  runId={runId}
                  artifactName={agent.output_file!}
                  label={agent.output_file!.split('/').pop()}
                />
              ))}
          </div>
        )}
        <ReviewActions stage={stage} runId={runId} workdir={workdir} onActionDone={onStageAction} />
        {stage.stage_id === 'develop' && stage.status === 'running' ? (
          <div className="terminal">
            {lines.map((line, index) => (
              <div className="terminalLine" key={`${line}-${index}`}>
                <span className="prompt">&gt;</span> {line}
              </div>
            ))}
            <span className="cursor" />
          </div>
        ) : null}
        {stage.quality_gates.length > 0 ? (
          <div className="gateList">
            {stage.quality_gates.map((gate) => {
              const gateStart = formatTime(gate.started_at);
              const gateEnd = formatTime(gate.completed_at);
              return (
              <div className="gateRow" key={gate.name}>
                <div>
                  <div className="gateName">{gate.name}</div>
                  {gate.command ? <div className="gateCommand">{gate.command}</div> : null}
                  {(gateStart || gate.retry_count) && (
                    <div className="gateDetail">
                      {gateStart && <span>{gateStart}{gateEnd ? ` → ${gateEnd}` : ''}</span>}
                      {gate.retry_count != null && gate.retry_count > 0 && <span>重试 {gate.retry_count} 次</span>}
                    </div>
                  )}
                </div>
                <StatusBadge status={gate.status} />
              </div>
              );
            })}
          </div>
        ) : null}
      </div>
    </section>
  );
}

export function PipelineTimeline({ run, liveLines = [], onStageAction }: {
  run: RunReport;
  liveLines?: string[];
  onStageAction: () => void;
}) {
  const wd = rememberedWorkdir(run.run_id) || run.project_root;
  return (
    <div className="timeline">
      {run.stages.map((stage) => (
        <StageCard
          stage={stage}
          liveLines={liveLines}
          runId={run.run_id}
          workdir={wd}
          onStageAction={onStageAction}
          key={`${stage.stage_id}-${stage.iteration ?? 1}`}
        />
      ))}
    </div>
  );
}
