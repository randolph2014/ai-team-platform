import { FileText } from 'lucide-react';
import { terminalLines } from '../lib/mockData';
import type { RunReport, StageRun } from '../lib/types';
import { StatusBadge } from './StatusBadge';

function StageCard({ stage, liveLines }: { stage: StageRun; liveLines: string[] }) {
  const lines = liveLines.length > 0 ? liveLines : terminalLines;
  return (
    <section className={`stageCard stage-${stage.status}`}>
      <header className="stageHeader">
        <div className="stageTitle">
          <span className="stageName">{stage.stage_name}</span>
          {stage.is_parallel && <span className="stageTag">parallel</span>}
          {stage.type === 'human_review' && <span className="stageTag">accept</span>}
        </div>
        <StatusBadge status={stage.status} />
      </header>
      <div className="stageBody">
        {stage.agents.map((agent) => (
          <div className="agentRow" key={`${stage.stage_id}-${agent.agent_name}`}>
            <div className="agentInfo">
              <div className="agentIcon">{agent.agent_name.slice(0, 2).toUpperCase()}</div>
              <div>
                <div className="agentName">{agent.agent_name}</div>
                <div className="agentRole">{agent.role ?? agent.provider}</div>
              </div>
            </div>
            <div className="agentMeta">
              {agent.duration_seconds ? <span>{Math.round(agent.duration_seconds)}s</span> : null}
              {agent.output_file ? (
                <span className="artifactLink">
                  <FileText size={13} /> {agent.output_file.split('/').pop()}
                </span>
              ) : null}
              <StatusBadge status={agent.status} />
            </div>
          </div>
        ))}
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
            {stage.quality_gates.map((gate) => (
              <div className="gateRow" key={gate.name}>
                <div>
                  <div className="gateName">{gate.name}</div>
                  {gate.command ? <div className="gateCommand">{gate.command}</div> : null}
                </div>
                <StatusBadge status={gate.status} />
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}

export function PipelineTimeline({ run, liveLines = [] }: { run: RunReport; liveLines?: string[] }) {
  return (
    <div className="timeline">
      {run.stages.map((stage) => (
        <StageCard stage={stage} liveLines={liveLines} key={`${stage.stage_id}-${stage.iteration ?? 1}`} />
      ))}
    </div>
  );
}
