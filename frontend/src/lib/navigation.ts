export function objectPath(type: string, id: string) {
  const paths: Record<string, string> = {
    project: "projects",
    projects: "projects",
    thread: "threads",
    research_threads: "threads",
    paper: "papers",
    papers: "papers",
    note: "notes",
    notes: "notes",
    task: "tasks",
    tasks: "tasks",
    evidence: "evidence",
    hypothesis: "hypotheses",
    hypotheses: "hypotheses",
    decision: "decisions",
    research_decisions: "decisions",
  };
  return paths[type] ? `/${paths[type]}/${id}` : "/settings/data";
}
