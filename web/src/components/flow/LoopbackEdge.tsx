import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';

export interface LoopbackEdgeData {
  trigger: string;
  maxRetries?: number;
  retryCount?: number;
}

export function LoopbackEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  markerEnd,
}: EdgeProps) {
  const edgeData = (data || {}) as unknown as LoopbackEdgeData;
  const [edgePath] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 8,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        className="flow-edge-loopback"
        style={{ stroke: 'var(--yellow)', strokeDasharray: '6 4', strokeWidth: 1.5 }}
        markerEnd={markerEnd}
      />
      {edgeData.trigger && (
        <foreignObject
          width={140}
          height={24}
          x={(sourceX + targetX) / 2 - 70}
          y={(sourceY + targetY) / 2 - 12}
          className="flow-edge-label-foreign"
          style={{ overflow: 'visible' }}
        >
          <div className="flow-edge-label loopback-label">
            {edgeData.trigger}
            {edgeData.maxRetries !== undefined && (
              <span className="loopback-retries">
                ({edgeData.retryCount || 0}/{edgeData.maxRetries})
              </span>
            )}
          </div>
        </foreignObject>
      )}
    </>
  );
}
