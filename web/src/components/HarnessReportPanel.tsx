import { AlertTriangle, CheckCircle, FileWarning, ShieldCheck, XCircle } from 'lucide-react';
import { MarkdownViewer } from './MarkdownViewer';
import type { HarnessReport, HarnessReportCheck } from '../lib/types';

interface HarnessReportPanelProps {
  report: HarnessReport;
}

function statusIcon(status: string) {
  if (status === 'pass') return <CheckCircle size={15} />;
  if (status === 'fail') return <XCircle size={15} />;
  return <AlertTriangle size={15} />;
}

function resultClass(check: HarnessReportCheck): string {
  if (check.status === 'fail') return 'harnessReportCheckFail';
  if (check.status === 'warning') return 'harnessReportCheckWarning';
  if (check.status === 'pass') return 'harnessReportCheckPass';
  return '';
}

function stringify(value: unknown): string {
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

export function HarnessReportPanel({ report }: HarnessReportPanelProps) {
  const blockingChecks = report.checks.filter((check) => check.blocking && check.status === 'fail');
  const warningChecks = report.checks.filter((check) => check.status === 'warning');

  return (
    <section className={`panel harnessReportPanel harnessReport-${report.status}`}>
      <div className="panelHeader">
        <h2><ShieldCheck size={16} /> Harness Report</h2>
        <span className={`badge badge-${report.status === 'fail' ? 'failed' : report.status === 'pass' ? 'passed' : 'warning'}`}>
          {report.status}
        </span>
      </div>

      <div className="harnessReportSummary">
        <span>Total <strong>{report.summary.total}</strong></span>
        <span>Passed <strong>{report.summary.passed}</strong></span>
        <span>Warnings <strong>{report.summary.warnings}</strong></span>
        <span>Failed <strong>{report.summary.failed}</strong></span>
        <span>Skipped <strong>{report.summary.skipped}</strong></span>
      </div>

      {report.blocking && blockingChecks.length > 0 ? (
        <div className="harnessReportBlock">
          <strong><FileWarning size={14} /> Blocking</strong>
          {blockingChecks.map((check) => (
            <span key={check.id}>{check.id}: {check.output_excerpt || check.status}</span>
          ))}
        </div>
      ) : null}

      {report.warnings.length > 0 || warningChecks.length > 0 ? (
        <div className="harnessReportWarnings">
          {report.warnings.map((warning) => <span key={warning}>{warning}</span>)}
          {warningChecks.map((check) => <span key={check.id}>{check.id}: {check.output_excerpt || 'warning'}</span>)}
        </div>
      ) : null}

      <div className="harnessReportChecks">
        {report.checks.map((check) => (
          <article className={`harnessReportCheck ${resultClass(check)}`} key={check.id}>
            <div className="harnessReportCheckHead">
              <span>{statusIcon(check.status)} <strong>{check.id}</strong></span>
              <span className="metaTag">{check.type}</span>
              <span className="metaTag">{check.severity}</span>
              {check.blocking ? <span className="metaTag metaTagDanger">blocking</span> : null}
            </div>
            {check.matched_files.length > 0 ? (
              <div className="harnessReportFiles">
                {check.matched_files.map((file) => <span className="metaTag" key={file}>{file}</span>)}
              </div>
            ) : null}
            {check.output_excerpt ? <pre>{check.output_excerpt}</pre> : null}
            {check.evidence_refs.length > 0 ? (
              <div className="harnessReportEvidenceRefs">
                {check.evidence_refs.map((ref) => <span className="mono" key={ref}>{ref}</span>)}
              </div>
            ) : null}
          </article>
        ))}
      </div>

      {report.baseline_results.length > 0 ? (
        <div className="harnessReportSection">
          <h3>Baseline Changes</h3>
          {report.baseline_results.map((item, index) => (
            <pre key={index}>{stringify(item)}</pre>
          ))}
        </div>
      ) : null}

      {report.rule_violations.length > 0 ? (
        <div className="harnessReportSection">
          <h3>Rule Violations</h3>
          {report.rule_violations.map((item, index) => (
            <pre key={index}>{stringify(item)}</pre>
          ))}
        </div>
      ) : null}

      {report.evidence.length > 0 ? (
        <div className="harnessReportSection">
          <h3>Evidence</h3>
          {report.evidence.map((item, index) => (
            <MarkdownViewer content={item} key={`${index}-${item.slice(0, 16)}`} />
          ))}
        </div>
      ) : null}
    </section>
  );
}
