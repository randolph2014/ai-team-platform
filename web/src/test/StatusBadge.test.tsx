import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StatusBadge } from '../components/StatusBadge';

describe('StatusBadge', () => {
  it('renders running status', () => {
    render(<StatusBadge status="running" />);
    const badge = screen.getByText('运行中');
    expect(badge).toBeInTheDocument();
    expect(badge.closest('.badge')).toHaveClass('badge-running');
  });

  it('renders completed status', () => {
    render(<StatusBadge status="completed" />);
    expect(screen.getByText('已完成')).toBeInTheDocument();
  });

  it('renders failed status', () => {
    render(<StatusBadge status="failed" />);
    expect(screen.getByText('失败')).toBeInTheDocument();
  });

  it('renders pending status', () => {
    render(<StatusBadge status="pending" />);
    expect(screen.getByText('等待中')).toBeInTheDocument();
  });

  it('renders waiting status', () => {
    render(<StatusBadge status="waiting" />);
    expect(screen.getByText('待验收')).toBeInTheDocument();
  });

  it('renders cancelled status', () => {
    render(<StatusBadge status="cancelled" />);
    expect(screen.getByText('已取消')).toBeInTheDocument();
  });

  it('renders unknown status as text', () => {
    render(<StatusBadge status="unknown-status" />);
    expect(screen.getByText('unknown-status')).toBeInTheDocument();
  });
});
