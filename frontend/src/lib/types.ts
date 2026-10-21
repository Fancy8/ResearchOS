import type { components } from "./generated-contracts";
export type User = components["Identity"];
export type Project = components["ProjectPublic"];
export type Thread = components["ResearchThreadPublic"];
export type Hypothesis = components["HypothesisPublic"];
export type Decision = components["ResearchDecisionPublic"];
export type Task = components["TaskPublic"];
export type Activity = components["ActivityEventPublic"];
export type Note = components["NotePublic"];
export type Dashboard = components["DashboardPublic"];
export const stages: Record<string, string> = {
  literature_review: "文献调研",
  planning: "方案设计",
  experimentation: "实验验证",
  writing: "论文写作",
  custom: "自定义",
};
export const statuses: Record<string, string> = {
  active: "进行中",
  paused: "暂停",
  archived: "已归档",
  draft: "草稿",
  proposed: "待验证",
  testing: "验证中",
  supported: "当前支持",
  contradicted: "当前反对",
  inconclusive: "暂无结论",
  todo: "待开始",
  doing: "进行中",
  done: "已完成",
  blocked: "受阻",
};
export const events: Record<string, string> = {
  project_created: "创建了研究课题",
  project_updated: "更新了课题",
  thread_created: "提出了研究问题",
  thread_updated: "更新了研究问题",
  hypothesis_created: "提出了研究假设",
  hypothesis_updated: "更新了假设判断",
  evidence_linked: "关联了研究证据",
  decision_created: "记录了研究决策",
  decision_revised: "修订了研究决策",
  task_created: "创建了研究任务",
  task_from_decision: "从决策创建了行动",
  task_completed: "完成了科研任务",
  task_reopened: "重新打开了任务",
  note_created: "创建了科研笔记",
  note_saved: "保存了科研笔记",
};
