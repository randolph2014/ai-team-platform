import { Handle, Position, type NodeProps } from '@xyflow/react';
import { ShieldCheck } from 'lucide-react';

export interface GateNodeData {
  name: string;
  gateType?: string;
  status?: string;
  required?: boolean;
  command?: string;
}

export function GateNode({ data }: NodeProps) {
  const nodeData = data as unknown as GateNodeData;
  const statusColor = {
    passed: 'var(--green)',
    failed: 'var(--red)',
    running: 'var(--blue)',
    pending: 'var(--text-muted)',
    warning: 'var(--yellow)',
  }[nodeData.status || 'pending'] || 'var(--text-muted)';

  return (
    <div
      className="flow-node gate-node"
      style={{ borderColor: statusColor }}
      data-status={nodeData.status || 'pending'}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flow-node-header">
        <ShieldCheck size={14} />
        <span>{nodeData.name}</span>
      </div>
      <div className="flow-node-body">
        <span className="flow-node-status" style={{ color: statusColor }}>
          {nodeData.status || 'pending'}
        </span>
        {nodeData.gateType && (
          <span className="flow-node-tag">{nodeData.gateType}</span>
        )}
        {nodeData.required && (
          <span className="flow-node-tag flow-node-tag-required">必要</span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
