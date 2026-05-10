import { FileText, Plus } from 'lucide-react';
import { useMemo, useState } from 'react';
import { MarkdownViewer } from './MarkdownViewer';
import type { HarnessFile } from '../lib/types';

interface HarnessAssetEditorProps {
  title: string;
  files: HarnessFile[];
  canEdit: boolean;
  onChange: (path: string, content: string) => void;
  onAdd?: () => void;
}

function isMarkdown(path: string): boolean {
  return /\.(md|markdown|mdx)$/i.test(path);
}

export function HarnessAssetEditor({ title, files, canEdit, onChange, onAdd }: HarnessAssetEditorProps) {
  const [activePath, setActivePath] = useState('');
  const activeFile = useMemo(() => {
    if (files.length === 0) return null;
    return files.find((file) => file.path === activePath) || files[0];
  }, [activePath, files]);

  return (
    <section className="harnessTabGrid">
      <aside className="harnessFileList">
        <div className="harnessFileListHeader">
          <h2>{title}</h2>
          {canEdit && onAdd ? (
            <button className="iconButton" onClick={onAdd} aria-label={`新增 ${title}`}>
              <Plus size={14} />
            </button>
          ) : null}
        </div>
        {files.length === 0 ? (
          <div className="harnessEmptyMini">暂无文件</div>
        ) : (
          files.map((file) => (
            <button
              key={file.path}
              className={`harnessFileItem ${activeFile?.path === file.path ? 'harnessFileItemActive' : ''}`}
              onClick={() => setActivePath(file.path)}
            >
              <FileText size={14} />
              <span>{file.path}</span>
            </button>
          ))
        )}
      </aside>

      <div className="harnessEditorPanel">
        {!activeFile ? (
          <div className="emptyState">
            <p>暂无 {title}</p>
          </div>
        ) : (
          <>
            <div className="harnessEditorHeader">
              <span className="mono">{activeFile.path}</span>
              {activeFile.hash ? <span className="metaTag">{activeFile.hash.slice(0, 18)}...</span> : null}
            </div>
            {canEdit ? (
              <textarea
                className="harnessTextarea"
                value={activeFile.content}
                onChange={(event) => onChange(activeFile.path, event.target.value)}
                spellCheck={false}
              />
            ) : (
              <pre className="harnessReadOnlyPre">{activeFile.content}</pre>
            )}
            {isMarkdown(activeFile.path) ? (
              <div className="harnessPreview">
                <MarkdownViewer content={activeFile.content} />
              </div>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}
