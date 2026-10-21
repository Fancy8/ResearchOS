"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { EditorContent, useEditor, type JSONContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Mathematics } from "@tiptap/extension-mathematics";
import "katex/dist/katex.min.css";
import {
  Bold,
  Italic,
  List,
  Quote,
  Heading2,
  Save,
  ArrowLeft,
  Plus,
} from "lucide-react";
import { api, ApiError, write } from "@/lib/api";
import { scopedKey } from "@/lib/query-client";
import type { User, Note } from "@/lib/types";
import { Button } from "./ui/button";
import { Empty, ErrorBox, FormDialog, Heading, Loading } from "./common";
import { NoteLinks } from "./note-links";
import { usePagedRows } from "@/lib/pagination";
import { PaginationControls } from "./pagination-controls";
import { ResearchCreateDialog } from "./research-create-dialog";

export function NotesPage({ user }: { user: User }) {
  const cache = useQueryClient();
  const [trash, setTrash] = useState(false);
  const [error, setError] = useState<unknown>();
  const notes = usePagedRows<Note>({
    queryKey: scopedKey(user.workspace_id, "notes", trash),
    path: `/notes?deleted=${trash}`,
  });
  return (
    <>
      <Heading
        eyebrow="RESEARCH NOTES"
        title={trash ? "笔记回收站" : "科研笔记"}
        text="写下你的理解与思考。笔记属于你，原始证据保留它的出处。"
        action={
          <ResearchCreateDialog
            workspaceId={user.workspace_id}
            kind="note"
            title="新建科研笔记"
            trigger={
              <span className="primary-trigger">
                <Plus size={16} />
                新建笔记
              </span>
            }
            fields={[{ name: "title", label: "笔记标题" }]}
          />
        }
      />
      <Button variant="outline" onClick={() => setTrash(!trash)}>
        {trash ? "返回科研笔记" : "查看回收站"}
      </Button>
      {Boolean(error) && <ErrorBox error={error} />}
      {notes.isPending ? (
        <Loading />
      ) : notes.error ? (
        <ErrorBox error={notes.error} />
      ) : notes.data.data.length ? (
        <div className="project-grid">
          {notes.data.data.map((note) => (
            <div className="project-card" key={note.id}>
              <span className="eyebrow">RESEARCH NOTE</span>
              <h2>
                {trash ? (
                  note.title
                ) : (
                  <Link href={`/notes/${note.id}`}>{note.title}</Link>
                )}
              </h2>
              <p>
                {new Date(note.last_saved_at).toLocaleString("zh-CN", {
                  timeZone: "Asia/Hong_Kong",
                })}
              </p>
              <span className="badge">已保存 · v{note.version}</span>
              {trash && (
                <Button
                  variant="outline"
                  onClick={async () => {
                    setError(undefined);
                    try {
                      const restored = await write<Note>(
                        `/notes/${note.id}/restore`,
                        "POST",
                        {
                          expected_version: note.version,
                        },
                      );
                      cache.setQueryData(
                        scopedKey(user.workspace_id, "note", note.id),
                        restored,
                      );
                      await cache.invalidateQueries({
                        queryKey: scopedKey(user.workspace_id, "notes"),
                      });
                    } catch (reason) {
                      setError(reason);
                    }
                  }}
                >
                  恢复笔记
                </Button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <Empty
          title={trash ? "回收站为空" : "留下你自己的研究思考"}
          text="支持标题、列表、引用、公式和自动保存。保存失败时保留本机草稿。"
        />
      )}
      <PaginationControls query={notes} label={trash ? "回收站笔记" : "笔记"} />
    </>
  );
}

export function NotePage({
  user,
  identifier,
}: {
  user: User;
  identifier: string;
}) {
  const note = useQuery({
    queryKey: scopedKey(user.workspace_id, "note", identifier),
    queryFn: () => api<Note>(`/notes/${identifier}`),
    refetchOnWindowFocus: false,
  });
  if (note.isPending) return <Loading />;
  if (note.error) return <ErrorBox error={note.error} />;
  return <NoteEditor key={identifier} user={user} initial={note.data.data} />;
}

function textContent(value: JSONContent): string {
  return value.text ?? (value.content ?? []).map(textContent).join("\n");
}

function NoteEditor({ user, initial }: { user: User; initial: Note }) {
  const router = useRouter();
  const [title, setTitle] = useState(initial.title);
  const [status, setStatus] = useState("已保存");
  const [error, setError] = useState<unknown>();
  const [conflict, setConflict] = useState<Note>();
  const [recovery, setRecovery] = useState<{
    title: string;
    content: JSONContent;
    version: number;
    timestamp: number;
  }>();
  const version = useRef(initial.version);
  const sequence = useRef(0);
  const dirty = useRef(false);
  const saving = useRef(false);
  const blocked = useRef(false);
  const latest = useRef({
    title: initial.title,
    content: initial.content as JSONContent,
  });
  const timer = useRef<ReturnType<typeof setTimeout>>(null);
  const saveRef = useRef<() => Promise<void>>(async () => {});
  const cache = useQueryClient();
  const draftKey = `researchos:draft:${user.workspace_id}:${initial.id}`;

  function stage(titleValue: string, content: JSONContent) {
    latest.current = { title: titleValue, content };
    sequence.current += 1;
    dirty.current = true;
    setStatus(blocked.current ? "版本冲突 · 草稿保留" : "待保存");
    try {
      localStorage.setItem(
        draftKey,
        JSON.stringify({
          ...latest.current,
          version: version.current,
          timestamp: Date.now(),
        }),
      );
    } catch {
      setError(
        new Error("本机草稿暂存不可用，请保持页面打开并确认服务器保存。"),
      );
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => saveRef.current(), 1000);
  }

  const editor = useEditor({
    extensions: [
      StarterKit,
      Mathematics.configure({
        katexOptions: { trust: false, throwOnError: false, maxExpand: 1000 },
        inlineOptions: {
          onClick: (node, pos) => {
            const latex = window.prompt(
              "编辑行内公式（LaTeX）",
              node.attrs.latex,
            );
            if (latex?.trim())
              editor
                ?.chain()
                .setNodeSelection(pos)
                .updateInlineMath({ latex })
                .focus()
                .run();
          },
        },
        blockOptions: {
          onClick: (node, pos) => {
            const latex = window.prompt(
              "编辑独立公式（LaTeX）",
              node.attrs.latex,
            );
            if (latex?.trim())
              editor
                ?.chain()
                .setNodeSelection(pos)
                .updateBlockMath({ latex })
                .focus()
                .run();
          },
        },
      }),
    ],
    content: initial.content as JSONContent,
    immediatelyRender: false,
    onUpdate: ({ editor }) => stage(latest.current.title, editor.getJSON()),
    editorProps: {
      attributes: { class: "note-prose", "aria-label": "笔记正文" },
    },
  });
  saveRef.current = async () => {
    if (saving.current || blocked.current || !dirty.current) return;
    saving.current = true;
    const sentSequence = sequence.current;
    const snapshot = { ...latest.current };
    setStatus("保存中…");
    setError(undefined);
    try {
      const result = await write<Note>(`/notes/${initial.id}`, "PUT", {
        ...snapshot,
        expected_version: version.current,
      });
      version.current = result.data.version;
      cache.setQueryData(
        scopedKey(user.workspace_id, "note", initial.id),
        result,
      );
      if (sentSequence === sequence.current) {
        dirty.current = false;
        setStatus(
          `已保存 · ${new Date(result.data.last_saved_at).toLocaleTimeString("zh-CN")}`,
        );
        localStorage.removeItem(draftKey);
      } else setStatus("待保存");
      cache.invalidateQueries({
        queryKey: scopedKey(user.workspace_id, "notes"),
      });
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        blocked.current = true;
        setStatus("版本冲突 · 草稿保留");
        try {
          setConflict((await api<Note>(`/notes/${initial.id}`)).data);
        } catch {}
      } else setStatus("保存失败 · 草稿保留");
      setError(reason);
    } finally {
      saving.current = false;
      if (
        sequence.current !== sentSequence &&
        dirty.current &&
        !blocked.current
      )
        timer.current = setTimeout(() => saveRef.current(), 1000);
    }
  };
  useEffect(() => {
    try {
      const data = JSON.parse(localStorage.getItem(draftKey) ?? "null");
      if (data && Date.now() - data.timestamp < 2 * 86400_000)
        setRecovery(data);
      else localStorage.removeItem(draftKey);
    } catch {
      localStorage.removeItem(draftKey);
    }
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty.current) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      if (timer.current) clearTimeout(timer.current);
      window.removeEventListener("beforeunload", warn);
    };
  }, [draftKey]);
  return (
    <>
      <Link href="/notes" className="breadcrumb">
        <ArrowLeft size={15} /> 返回笔记
      </Link>
      <div className="note-heading">
        <input
          aria-label="笔记标题"
          value={title}
          onChange={(event) => {
            setTitle(event.target.value);
            stage(
              event.target.value,
              editor?.getJSON() ?? latest.current.content,
            );
          }}
        />
        <span className="note-save-state" role="status">
          {status}
        </span>
        <Button
          variant="outline"
          onClick={() => saveRef.current()}
          disabled={blocked.current}
        >
          <Save size={15} />
          立即保存
        </Button>
        <Button
          variant="outline"
          disabled={Boolean(conflict) || Boolean(recovery)}
          onClick={async () => {
            await saveRef.current();
            if (dirty.current || saving.current || blocked.current) {
              setError(new Error("请先确认当前笔记保存成功，再移入回收站。"));
              return;
            }
            if (
              !window.confirm(
                "将笔记移入回收站？决策历史中的笔记快照会继续保留。",
              )
            )
              return;
            try {
              await write(`/notes/${initial.id}`, "DELETE", {
                expected_version: version.current,
              });
              localStorage.removeItem(draftKey);
              await cache.invalidateQueries({
                queryKey: scopedKey(user.workspace_id, "notes"),
              });
              router.push("/notes");
            } catch (reason) {
              setError(reason);
            }
          }}
        >
          移入回收站
        </Button>
      </div>
      {recovery && (
        <div className="draft-recovery">
          <strong>检测到本机未提交草稿</strong>
          <p>
            {new Date(recovery.timestamp).toLocaleString("zh-CN")} ·{" "}
            {recovery.version === version.current
              ? "与当前服务器版本一致"
              : "基于旧版本，恢复后需要比较和确认"}
          </p>
          <Button
            variant="outline"
            onClick={() => {
              setTitle(recovery.title);
              editor?.commands.setContent(recovery.content, {
                emitUpdate: false,
              });
              latest.current = {
                title: recovery.title,
                content: recovery.content,
              };
              if (recovery.version !== version.current) {
                blocked.current = true;
                setConflict(initial);
              }
              stage(recovery.title, recovery.content);
              setRecovery(undefined);
            }}
          >
            恢复到编辑区
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              localStorage.removeItem(draftKey);
              setRecovery(undefined);
            }}
          >
            丢弃本机草稿
          </Button>
        </div>
      )}
      {conflict && (
        <div className="conflict-panel">
          <h2>另一个页面修改了这份笔记</h2>
          <p>你的输入仍在编辑区。先比较服务器内容，再选择如何处理。</p>
          <blockquote>
            <strong>{conflict.title}</strong>
            <p>{textContent(conflict.content as JSONContent)}</p>
          </blockquote>
          <Button
            variant="outline"
            onClick={() => {
              setTitle(conflict.title);
              editor?.commands.setContent(conflict.content as JSONContent, {
                emitUpdate: false,
              });
              latest.current = {
                title: conflict.title,
                content: conflict.content as JSONContent,
              };
              version.current = conflict.version;
              dirty.current = false;
              blocked.current = false;
              localStorage.removeItem(draftKey);
              setConflict(undefined);
              setError(undefined);
              setStatus("已加载服务器内容");
            }}
          >
            使用服务器内容
          </Button>
          <Button
            onClick={async () => {
              const current = (await api<Note>(`/notes/${initial.id}`)).data;
              if (current.version !== conflict.version) {
                setConflict(current);
                return;
              }
              version.current = current.version;
              blocked.current = false;
              setConflict(undefined);
              dirty.current = true;
              await saveRef.current();
            }}
          >
            确认保留编辑区内容并保存
          </Button>
        </div>
      )}
      {Boolean(error) && (
        <ErrorBox error={error} retry={() => saveRef.current()} />
      )}
      <section className="note-editor">
        <div className="note-toolbar">
          <FormDialog
            title="插入数学公式"
            trigger={<span>公式</span>}
            fields={[
              { name: "latex", label: "LaTeX 公式", type: "textarea" },
              {
                name: "kind",
                label: "公式类型",
                type: "select",
                options: { inline: "行内公式", block: "独立公式" },
              },
            ]}
            onSubmit={async (values) => {
              if (values.latex.length > 5000)
                throw new Error("公式最多支持 5000 字符");
              if (values.kind === "block")
                editor
                  ?.chain()
                  .focus()
                  .insertBlockMath({ latex: values.latex })
                  .run();
              else
                editor
                  ?.chain()
                  .focus()
                  .insertInlineMath({ latex: values.latex })
                  .run();
            }}
          />
          {[
            ["加粗", Bold, () => editor?.chain().focus().toggleBold().run()],
            [
              "斜体",
              Italic,
              () => editor?.chain().focus().toggleItalic().run(),
            ],
            [
              "二级标题",
              Heading2,
              () => editor?.chain().focus().toggleHeading({ level: 2 }).run(),
            ],
            [
              "项目列表",
              List,
              () => editor?.chain().focus().toggleBulletList().run(),
            ],
            [
              "引用",
              Quote,
              () => editor?.chain().focus().toggleBlockquote().run(),
            ],
          ].map(([label, Icon, action]) => {
            const Symbol = Icon as typeof Bold;
            return (
              <Button
                key={String(label)}
                variant="ghost"
                size="icon"
                aria-label={String(label)}
                onClick={action as () => void}
              >
                <Symbol size={17} />
              </Button>
            );
          })}
          <span>输入停止后自动保存</span>
        </div>
        <EditorContent editor={editor} />
      </section>
      <NoteLinks user={user} noteId={initial.id} />
    </>
  );
}
