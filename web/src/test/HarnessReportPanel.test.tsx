import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { HarnessReportPanel } from '../components/HarnessReportPanel';
import type { HarnessReport } from '../lib/types';

const report: HarnessReport = {
  schema_version: '1.0',
  run_id: 'run-harness-ui',
  project_id: 'proj-1',
  stage_id: 'harness_verify',
  harness_config_hash: 'sha256:manifest',
  generated_at: '2026-05-10T00:00:00Z',
  status: 'fail',
  blocking: true,
  summary: { total: 3, passed: 1, warnings: 1, failed: 1, skipped: 0 },
  checks: [
    {
      id: 'warn.docs',
      type: 'pattern',
      status: 'warning',
      severity: 'warning',
      blocking: false,
      duration_ms: 5,
      exit_code: null,
      matched_files: ['docs/spec.md'],
      output_excerpt: '1 pattern match',
      evidence_refs: ['docs/spec.md:4'],
    },
    {
      id: 'block.security',
      type: 'command',
      status: 'fail',
      severity: 'error',
      blocking: true,
      duration_ms: 10,
      exit_code: 1,
      matched_files: [],
      output_excerpt: 'security gate failed',
      evidence_refs: ['quality_gate:block.security'],
    },
  ],
  baseline_results: [
    { check_id: 'baseline.coverage', changes: [{ metric: 'coverage', previous: 90, current: 88 }] },
  ],
  rule_violations: [
    { rule_id: 'no-messagebox', file: 'src/App.tsx', line: 12 },
  ],
  warnings: ['non-blocking warning'],
  evidence: ['# Evidence Body\n\n<script>window.__xss = true</script><img src=x onerror="window.__xss = true">'],
  next_stage_contract: {},
};

describe('HarnessReportPanel', () => {
  it('shows blocking failures, warnings, baseline changes, and sanitized evidence', () => {
    render(<HarnessReportPanel report={report} />);

    expect(screen.getByText('Harness Report')).toBeInTheDocument();
    expect(screen.getByText(/block.security: security gate failed/)).toBeInTheDocument();
    expect(screen.getByText(/warn.docs: 1 pattern match/)).toBeInTheDocument();
    expect(screen.getByText('Baseline Changes')).toBeInTheDocument();
    expect(screen.getByText('Rule Violations')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Evidence' })).toBeInTheDocument();
    expect(document.querySelector('script')).toBeNull();
    expect(document.querySelector('[onerror]')).toBeNull();
  });
});
