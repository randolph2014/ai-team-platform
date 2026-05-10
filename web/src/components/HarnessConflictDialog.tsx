import { AlertTriangle, RefreshCw, X } from 'lucide-react';
import type { HarnessConflictPayload } from '../lib/types';

interface HarnessConflictDialogProps {
  conflict: HarnessConflictPayload;
  onRefresh: () => void;
  onClose: () => void;
}

export function HarnessConflictDialog({ conflict, onRefresh, onClose }: HarnessConflictDialogProps) {
  return (
    <div className="modalOverlay" role="dialog" aria-modal="true">
      <div className="modal">
        <div className="modalHeader">
          <h2><AlertTriangle size={18} /> Manifest 冲突</h2>
          <button className="iconButton" onClick={onClose} aria-label="关闭">
            <X size={16} />
          </button>
        </div>
        <div className="conflictSummary">
          <div className="configEntry">
            <span className="configKey">current_manifest_hash</span>
            <span className="configValue mono">{conflict.current_manifest_hash}</span>
          </div>
          {conflict.changed_files.length > 0 && (
            <div className="conflictFiles">
              {conflict.changed_files.map((file) => (
                <span className="metaTag" key={file}>{file}</span>
              ))}
            </div>
          )}
        </div>
        <div className="modalActions">
          <button className="button" onClick={onClose}>关闭</button>
          <button className="button primary" onClick={onRefresh}>
            <RefreshCw size={14} /> 刷新
          </button>
        </div>
      </div>
    </div>
  );
}
