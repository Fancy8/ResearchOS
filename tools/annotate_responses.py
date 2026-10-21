"""Apply explicit, reviewed response DTOs without modifying function bodies."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = {
    "research": {
        "projects": "PageEnvelope[ProjectPublic]", "project_create": "Envelope[ProjectPublic]", "project_get": "Envelope[ProjectPublic]", "project_patch": "Envelope[ProjectPublic]", "set_default": "Envelope[ProjectPublic]",
        "threads": "PageEnvelope[ThreadPublic]", "thread_create": "Envelope[ThreadPublic]", "thread_get": "Envelope[ThreadPublic]", "thread_patch": "Envelope[ThreadPublic]", "revisions": "Envelope[list[ThreadRevisionPublic]]",
    },
    "workflow": {
        "hypotheses": "PageEnvelope[HypothesisPublic]", "hypothesis_create": "Envelope[HypothesisPublic]", "hypothesis_get": "Envelope[HypothesisPublic]", "hypothesis_patch": "Envelope[HypothesisPublic]", "hypothesis_revisions": "Envelope[list[HypothesisRevisionPublic]]",
        "decisions": "PageEnvelope[DecisionPublic]", "decision_create": "Envelope[DecisionPublic]", "decision_get": "Envelope[DecisionPublic]", "decision_revisions": "Envelope[list[DecisionRevisionPublic]]", "decision_revision": "Envelope[DecisionRevisionPublic]", "decision_revise": "Envelope[DecisionPublic]",
        "tasks": "PageEnvelope[TaskPublic]", "task_create": "Envelope[TaskPublic]", "task_get": "Envelope[TaskPublic]", "task_patch": "Envelope[TaskPublic]", "notes": "PageEnvelope[NotePublic]", "note_create": "Envelope[NotePublic]", "note_get": "Envelope[NotePublic]", "note_save": "Envelope[NotePublic]", "note_restore": "Envelope[NotePublic]",
    },
    "evidence": {"list_evidence": "PageEnvelope[EvidencePublic]", "evidence_create": "Envelope[EvidencePublic]", "evidence_get": "Envelope[EvidencePublic]", "evidence_patch": "Envelope[EvidencePublic]", "evidence_reuse": "Envelope[EvidencePublic]"},
    "identity": {"me": "Envelope[Identity]", "profile": "Envelope[ProfilePublic]", "update_profile": "Envelope[ProfilePublic]"},
    "papers": {"papers": "PageEnvelope[PaperPublic]", "paper_create": "Envelope[PaperPublic]", "paper_get": "Envelope[PaperPublic]", "paper_patch": "Envelope[PaperPublic]", "files": "Envelope[list[FilePublic]]"},
    "account_actions": {"request_reset": "Envelope[Message]", "request_verification": "Envelope[Message]", "reset_password": "Envelope[Message]", "verify_email": "Envelope[Message]"},
}


for module, contracts in CONTRACTS.items():
    path = ROOT / f"backend/app/api/{module}.py"
    source = path.read_text(encoding="utf-8")
    tree, edits, imports, used = ast.parse(source), [], set(), set()
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    for function in tree.body:
        if not isinstance(function, ast.AsyncFunctionDef) or function.name not in contracts:
            continue
        model = contracts[function.name]
        for token in ast.walk(ast.parse(model, mode="eval")):
            if isinstance(token, ast.Name) and token.id != "list":
                imports.add(token.id)
        decorator = next(node for node in function.decorator_list if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "router")
        used.add(function.name)
        if not any(keyword.arg == "response_model" for keyword in decorator.keywords):
            end = offsets[decorator.end_lineno - 1] + decorator.end_col_offset - 1
            edits.append((end, f", response_model={model}"))
    missing = contracts.keys() - used
    if missing:
        raise RuntimeError(f"Unmatched reviewed endpoint functions: {module} {sorted(missing)}")
    for position, inserted in sorted(edits, reverse=True):
        source = source[:position] + inserted + source[position:]
    if edits:
        source = "from app.responses import " + ", ".join(sorted(imports)) + "\n" + source
        path.write_text(source, encoding="utf-8")
