// @ts-expect-error Vitest executes this contract test in Node; app tsconfig intentionally omits Node globals.
import { readFileSync } from 'node:fs';
// @ts-expect-error Vitest executes this contract test in Node; app tsconfig intentionally omits Node globals.
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const nodeProcess = (globalThis as unknown as { process: { cwd(): string } }).process;
const styles = readFileSync(resolve(nodeProcess.cwd(), 'src/styles.css'), 'utf8');

describe('sidebar navigation style contract', () => {
  it('styles NavLink anchors with the same row layout as sidebar actions', () => {
    expect(styles).toMatch(/\.sidebar nav a[^{]*\{[^}]*display:\s*flex;[^}]*align-items:\s*center;[^}]*gap:\s*10px;/s);
    expect(styles).toMatch(/\.sidebar nav a\.active\s*\{[^}]*background:\s*var\(--accent\);[^}]*color:\s*#fff;/s);
    expect(styles).toMatch(/\.brand span,\s*\.sidebar nav a span,\s*\.navSection\s*\{[^}]*display:\s*none;/s);
  });
});
