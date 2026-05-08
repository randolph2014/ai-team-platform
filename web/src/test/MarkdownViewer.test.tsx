import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MarkdownViewer } from '../components/MarkdownViewer';

describe('MarkdownViewer security', () => {
  it('renders sanitized markdown content', () => {
    render(<MarkdownViewer content={'# 标题\n\n<script>window.__xss = true</script><img src=x onerror="window.__xss = true">'} />);

    expect(screen.getByRole('heading', { name: '标题' })).toBeInTheDocument();
    expect(document.querySelector('script')).toBeNull();
    expect(document.querySelector('[onerror]')).toBeNull();
  });
});
