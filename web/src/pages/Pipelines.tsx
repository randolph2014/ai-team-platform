import { Boxes, GitBranch, ShieldCheck } from 'lucide-react';

const templates = [
  ['iOS 标准交付', 'SwiftUI / SPM / swift test / code review'],
  ['Web 标准交付', 'React / TypeScript / build / unit test'],
  ['后端服务标准交付', 'API schema / database migration / integration test'],
];

export function Pipelines() {
  return (
    <div className="page">
      <header className="pageHeader"><h1>Pipeline 模板</h1></header>
      <div className="pipelineGrid">
        {templates.map(([name, description], index) => {
          const Icon = index === 0 ? ShieldCheck : index === 1 ? Boxes : GitBranch;
          return (
            <section className="pipelineCard" key={name}>
              <Icon size={20} />
              <h2>{name}</h2>
              <p>{description}</p>
              <div className="pipelineStats"><span>7 stages</span><span>quality gates</span><span>worktree</span></div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
