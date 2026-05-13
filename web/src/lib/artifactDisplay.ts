const ARTIFACT_LABELS: Record<string, string> = {
  'requirement-final.json': 'Task Contract',
};

export function artifactDisplayName(name: string): string {
  return ARTIFACT_LABELS[name] || name;
}

export function artifactDisplaySubtitle(name: string): string {
  const label = artifactDisplayName(name);
  return label === name ? '' : name;
}
