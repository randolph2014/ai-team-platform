import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Bot } from 'lucide-react';

export interface AgentNodeData {
  name: string;
  provider?: string;
  model?: string;
  role?: string;
  status?: string;
}

export function AgentNode({ data }: NodeProps) {
  const nodeData = data as unknown as AgentNodeData;
  const statusColor = {
    completed: 'var(--green)',
    running: 'var(--blue)',
    failed: 'var(--red)',
    pending: 'var(--text-muted)',
  }[nodeData.status || 'pending'] || 'var(--text-muted)';

  return (
    <div
      className="flow-node agent-node"
      style={{ borderColor: statusColor }}
      data-status={nodeData.status || 'pending'}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flow-node-header">
        <Bot size={14} />
        <span>{nodeData.name}</span>
      </div>
      <div className="flow-node-body">
        {nodeData.provider && (
          <span className="flow-node-tag flow-node-tag-provider">{nodeData.provider}</span>
        )}
        {nodeData.model && (
          <span className="flow-node-tag flow-node-tag-model">{nodeData.model}</span>
        )}
        {nodeData.role && (
          <span className="flow-node-tag flow-node-tag-role">{nodeData.role}</span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
