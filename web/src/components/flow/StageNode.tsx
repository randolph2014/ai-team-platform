import { Handle, Position, type NodeProps } from '@xyflow/react';
import { FlagTriangleRight } from 'lucide-react';

export interface StageNodeData {
  name: string;
  status?: string;
  is_parallel?: boolean;
  iteration?: number;
  agentCount?: number;
  hasLoopback?: boolean;
}

export function StageNode({ data }: NodeProps) {
  const nodeData = data as unknown as StageNodeData;
  const statusColor = {
    completed: 'var(--green)',
    running: 'var(--blue)',
    failed: 'var(--red)',
    pending: 'var(--text-muted)',
    skipped: 'var(--text-muted)',
  }[nodeData.status || 'pending'] || 'var(--text-muted)';

  return (
    <div
      className="flow-node stage-node"
      style={{ borderColor: statusColor }}
      data-status={nodeData.status || 'pending'}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flow-node-header">
        <FlagTriangleRight size={14} />
        <span>{nodeData.name}</span>
      </div>
      <div className="flow-node-body">
        {nodeData.status && (
          <span className="flow-node-status" style={{ color: statusColor }}>
            {nodeData.status}
          </span>
        )}
        {nodeData.agentCount !== undefined && (
          <span className="flow-node-tag">{nodeData.agentCount} agents</span>
        )}
        {nodeData.is_parallel && (
          <span className="flow-node-tag flow-node-tag-parallel">并行</span>
        )}
        {nodeData.hasLoopback && (
          <span className="flow-node-tag flow-node-tag-loopback">回环</span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
