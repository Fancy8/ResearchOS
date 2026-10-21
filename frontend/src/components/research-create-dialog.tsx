"use client";
import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { ApiError } from "@/lib/api";
import { researchRequest, SAFE_REPLAY_AGE_MS } from "@/lib/research-request";
import {
  CreationStorageError,
  checkCreated,
  creationEndpoint,
  creationKey,
  creationObjectPath,
  readCreation,
  sameCreation,
  saveCreation,
  type CreationKind,
  type CreationRecord,
} from "@/lib/research-creation";
import { Button } from "./ui/button";
import { ErrorBox, type Field } from "./common";

export function ResearchCreateDialog({
  workspaceId,
  kind,
  parent,
  title,
  trigger,
  fields,
}: {
  workspaceId: string;
  kind: CreationKind;
  parent?: { id: string; title: string };
  title: string;
  trigger: React.ReactNode;
  fields: Field[];
}) {
  const cache = useQueryClient();
  const router = useRouter();
  const formId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const defaults = () =>
    Object.fromEntries(
      fields.map((field) => [
        field.name,
        field.default ??
          (field.type === "select"
            ? (Object.keys(field.options ?? {})[0] ?? "")
            : ""),
      ]),
    );
  const [draft, setDraft] = useState<Record<string, string>>(defaults);
  const [record, setRecord] = useState<CreationRecord>();
  const original = useRef<CreationRecord | undefined>(undefined);
  const [loaded, setLoaded] = useState(false);
  const [pending, setPending] = useState(false);
  const [owns, setOwns] = useState(false);
  const [storageBlocked, setStorageBlocked] = useState(false);
  const [error, setError] = useState<unknown>();
  const [readError, setReadError] = useState<unknown>();
  const [storageError, setStorageError] = useState<unknown>();
  const [latest, setLatest] = useState<{ title: string; version: number }>();
  const alive = useRef(false);
  const generation = useRef(0);
  const busy = useRef(false);
  const owner = useRef<string | null>(null);
  const opening = useRef(false);
  const release = useRef<(() => void) | undefined>(undefined);
  function adopt(value?: CreationRecord) {
    const old = original.current;
    if (value) {
      if (!(
        old?.phase === "editable" &&
        value.phase === "editable" &&
        sameCreation(old, value)
      ))
        setDraft({ ...value.body });
    } else if (old) setDraft(defaults());
    original.current = value;
    setRecord(value);
  }
  function sync() {
    try {
      let fresh = readCreation(workspaceId, kind);
      const known = original.current;
      if (
        fresh &&
        known &&
        fresh.key === known.key &&
        known.phase === "accepted"
      ) {
        if (
          !sameCreation(fresh, known) ||
          (fresh.phase === "accepted" && fresh.resourceId !== known.resourceId)
        )
          throw new Error("本机恢复记录与已确认创建不一致，请先核对已有记录。");
        fresh = known;
      } else if (
        fresh?.phase === "unknown" &&
        known?.phase === "editable" &&
        sameCreation(fresh, known)
      )
        fresh = known;
      adopt(fresh);
      setStorageBlocked(false);
      return fresh;
    } catch (reason) {
      setStorageBlocked(true);
      throw reason;
    }
  }
  useEffect(() => {
    alive.current = true;
    generation.current++;
    try {
      sync();
    } catch (reason) {
      setError(reason);
    }
    setLoaded(true);
    const changed = (event: StorageEvent) => {
      if (event.key !== creationKey(workspaceId, kind) && event.key !== null)
        return;
      generation.current++;
      busy.current = false;
      setPending(false);
      setLatest(undefined);
      setReadError(undefined);
      setStorageError(undefined);
      try {
        sync();
        setError(undefined);
      } catch (reason) {
        setError(reason);
      }
    };
    window.addEventListener("storage", changed);
    return () => {
      alive.current = false;
      generation.current++;
      release.current?.();
      dialog.current?.close();
      window.removeEventListener("storage", changed);
    };
    // Draft and lock lifetimes belong to the authenticated workspace and entity kind.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, kind]);
  async function open() {
    if (dialog.current?.open) return;
    if (owner.current) {
      dialog.current?.showModal();
      return;
    }
    if (opening.current) return;
    opening.current = true;
    const token = generation.current;
    const lease = crypto.randomUUID();
    try {
      if (!navigator.locks)
        throw new Error(
          "当前浏览器不支持安全的多窗口创建恢复，请使用受支持的浏览器。",
        );
      await navigator.locks.request(
        `researchos.create.${workspaceId}.${kind}`,
        { mode: "exclusive", ifAvailable: true },
        async (lock) => {
          if (!alive.current || token !== generation.current) return;
          if (!lock) {
            setOwns(false);
            setError(
              new Error(
                "另一个标签页正在编辑或保存这类创建请求。请先关闭或完成那个窗口，再重新打开。",
              ),
            );
            dialog.current?.showModal();
            return;
          }
          owner.current = lease;
          setOwns(true);
          try {
            sync();
          } catch (reason) {
            setError(reason);
          }
          dialog.current?.showModal();
          await new Promise<void>((resolve) => {
            release.current = () => {
              if (owner.current === lease) {
                owner.current = null;
                if (alive.current) setOwns(false);
              }
              release.current = undefined;
              resolve();
            };
          });
        },
      );
    } catch (reason) {
      if (alive.current && token === generation.current) {
        setError(reason);
        dialog.current?.showModal();
      }
    } finally {
      opening.current = false;
      if (owner.current === lease) {
        owner.current = null;
        if (alive.current) setOwns(false);
      }
    }
  }
  async function act(
    action: (
      fresh: CreationRecord | undefined,
      active: () => boolean,
    ) => Promise<void>,
    options: { read?: boolean; corrupt?: boolean } = {},
  ) {
    if (busy.current) return;
    if (!owner.current) {
      setError(new Error("当前窗口尚未取得编辑权，请关闭后重新打开。"));
      return;
    }
    busy.current = true;
    setPending(true);
    if (options.read) setReadError(undefined);
    else setError(undefined);
    const token = generation.current;
    const expected = original.current;
    const active = () => alive.current && token === generation.current;
    try {
      const fresh = options.corrupt ? undefined : sync();
      if (
        !options.corrupt &&
        expected &&
        (!fresh || fresh.key !== expected.key)
      )
        throw new Error("原创建记录已在其他窗口改变，请先核对当前输入。");
      if (active()) await action(fresh, active);
    } catch (reason) {
      if (active()) {
        if (options.read) setReadError(reason);
        else setError(reason);
      }
    } finally {
      if (active()) {
        busy.current = false;
        setPending(false);
        if (!dialog.current?.open) release.current?.();
      }
    }
  }
  function persist(value: CreationRecord) {
    try {
      saveCreation(value);
      setStorageBlocked(false);
      setStorageError(undefined);
    } catch (reason) {
      if (reason instanceof CreationStorageError) setStorageBlocked(true);
      throw reason;
    }
    adopt(value);
    return value;
  }
  async function submit() {
    const body = { ...draft };
    const target = {
      parentId: kind === "thread" ? (parent?.id ?? null) : null,
      contextTitle:
        kind === "thread"
          ? (parent?.title ?? "尚未取得目标课题")
          : "个人科研空间",
    };
    await act(async (fresh, active) => {
      if (fresh?.phase === "accepted") return;
      let intent: CreationRecord =
        fresh?.phase === "unknown"
          ? fresh
          : fresh
            ? { ...fresh, body, phase: "unknown" }
            : {
                version: 1,
                workspaceId,
                kind,
                key: crypto.randomUUID(),
                createdAt: Date.now(),
                ...target,
                body,
                phase: "unknown",
              };
      if (Date.now() - intent.createdAt >= SAFE_REPLAY_AGE_MS)
        throw new Error(
          "原创建请求已超过可安全重试时限，请先核对已有记录，再决定是否结束此次恢复。",
        );
      intent = persist(intent);
      try {
        const resource = checkCreated(
          (
            await researchRequest<unknown>(
              creationEndpoint(intent),
              "POST",
              intent.body,
              intent.key,
            )
          ).data,
          intent,
        );
        if (!active()) return;
        const accepted: CreationRecord = {
          ...intent,
          phase: "accepted",
          resourceId: resource.id,
        };
        adopt(accepted);
        setLatest(undefined);
        let saved = true;
        try {
          persist(accepted);
        } catch (reason) {
          saved = false;
          setStorageError(reason);
        }
        void cache.invalidateQueries({ queryKey: ["workspace", workspaceId] });
        if (saved && dialog.current?.open) {
          dialog.current.close();
          router.push(creationObjectPath(accepted));
        }
      } catch (reason) {
        if (
          active() &&
          reason instanceof ApiError &&
          [
            "VALIDATION_ERROR",
            "INVALID_NOTE_DOCUMENT",
            "RESOURCE_NOT_FOUND",
          ].includes(reason.code) &&
          [404, 422].includes(reason.status)
        ) {
          const editable: CreationRecord = { ...intent, phase: "editable" };
          adopt(editable);
          try {
            persist(editable);
          } catch (storage) {
            setStorageError(storage);
          }
        }
        throw reason;
      }
    });
  }
  async function read() {
    await act(
      async (fresh, active) => {
        if (fresh?.phase !== "accepted") {
          try {
            sync();
          } catch (reason) {
            setReadError(reason);
          }
          return;
        }
        const result = checkCreated(
          (await researchRequest<unknown>(creationObjectPath(fresh))).data,
          fresh,
          fresh.resourceId,
        );
        if (!active()) return;
        setLatest({ title: result.title, version: result.version });
        try {
          persist(fresh);
        } catch (reason) {
          setStorageError(reason);
        }
      },
      { read: true },
    );
  }
  async function next() {
    await act(async (fresh) => {
      if (!fresh || fresh.phase === "unknown") return;
      const corrected = fresh.phase === "editable" ? { ...draft } : defaults();
      localStorage.removeItem(creationKey(workspaceId, kind));
      adopt(undefined);
      setDraft(corrected);
      setLatest(undefined);
      setReadError(undefined);
      setStorageError(undefined);
      setStorageBlocked(false);
    });
  }
  async function forget() {
    await act(
      async () => {
        localStorage.removeItem(creationKey(workspaceId, kind));
        adopt(undefined);
        setDraft(defaults());
        setLatest(undefined);
        setReadError(undefined);
        setStorageError(undefined);
        setStorageBlocked(false);
      },
      { corrupt: true },
    );
  }
  const frozen = record?.phase === "unknown" || record?.phase === "accepted";
  const list =
    kind === "thread"
      ? `/projects/${record?.parentId ?? parent?.id}`
      : kind === "project"
        ? "/projects"
        : "/notes";
  return (
    <>
      <button
        type="button"
        className="dialog-trigger"
        disabled={!loaded}
        onClick={open}
      >
        {trigger}
      </button>
      <dialog
        ref={dialog}
        className="form-dialog research-create-dialog"
        aria-labelledby={`${formId}-title`}
        onClose={() => {
          if (!dialog.current?.open && !busy.current) release.current?.();
        }}
      >
        <div className="dialog-heading">
          <h2 id={`${formId}-title`}>{title}</h2>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="关闭"
            onClick={() => dialog.current?.close()}
          >
            <X size={20} />
          </Button>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <p className="creation-context">
            {record ? "原创建目标" : "新建目标"}：
            {record?.contextTitle ??
              (kind === "thread" ? parent?.title : "个人科研空间")}
          </p>
          <p className="muted creation-privacy">
            本次提交的输入会保留在此浏览器，退出登录时清除。
          </p>
          <fieldset disabled={!owns || pending || storageBlocked || frozen}>
            {fields.map((field) => (
              <div className="field" key={field.name}>
                <label htmlFor={`${formId}-${field.name}`}>
                  {field.label}
                  {field.required !== false && (
                    <span aria-hidden="true"> *</span>
                  )}
                </label>
                {field.type === "textarea" ? (
                  <textarea
                    id={`${formId}-${field.name}`}
                    name={field.name}
                    aria-label={field.label}
                    value={draft[field.name] ?? ""}
                    required={field.required !== false}
                    maxLength={20000}
                    rows={4}
                    onChange={(event) =>
                      setDraft((values) => ({
                        ...values,
                        [field.name]: event.target.value,
                      }))
                    }
                  />
                ) : field.type === "select" ? (
                  <select
                    id={`${formId}-${field.name}`}
                    name={field.name}
                    aria-label={field.label}
                    value={draft[field.name] ?? ""}
                    required={field.required !== false}
                    onChange={(event) =>
                      setDraft((values) => ({
                        ...values,
                        [field.name]: event.target.value,
                      }))
                    }
                  >
                    {Object.entries(field.options ?? {}).map(
                      ([value, text]) => (
                        <option key={value} value={value}>
                          {text}
                        </option>
                      ),
                    )}
                  </select>
                ) : (
                  <input
                    id={`${formId}-${field.name}`}
                    name={field.name}
                    aria-label={field.label}
                    value={draft[field.name] ?? ""}
                    required={field.required !== false}
                    maxLength={250}
                    onChange={(event) =>
                      setDraft((values) => ({
                        ...values,
                        [field.name]: event.target.value,
                      }))
                    }
                  />
                )}
              </div>
            ))}
          </fieldset>
          {record?.phase === "unknown" && (
            <p role="status">
              创建结果尚未确认。重试保留原目标、输入和请求，不另建一条记录。
            </p>
          )}
          {record?.phase === "editable" && (
            <p>上次请求已明确拒绝，可修正输入后保存；目标仍是上方原目标。</p>
          )}
          {record?.phase === "accepted" && (
            <div className="creation-confirmed">
              <p role="status">创建已确认。详情读取失败时不需要重新创建。</p>
              <p>上方为创建时输入，当前信息以后续读取为准。</p>
              <Link href={creationObjectPath(record)}>打开已创建记录</Link>
              <Button
                type="button"
                variant="outline"
                disabled={pending || !owns}
                onClick={read}
              >
                读取已创建记录
              </Button>
              {latest && (
                <p>
                  最近一次读取：{latest.title} · v{latest.version}
                </p>
              )}
              <Button
                type="button"
                variant="outline"
                disabled={pending || !owns}
                onClick={next}
              >
                新建另一条
              </Button>
            </div>
          )}
          {Boolean(error) && <ErrorBox error={error} />}
          {Boolean(readError) && (
            <>
              <p>读取暂未完成，原创建确认仍保留。</p>
              <ErrorBox error={readError} />
            </>
          )}
          {Boolean(storageError) && (
            <>
              <p>服务器结果已确认，本机恢复记录暂未保存。请先核对已有记录。</p>
              <ErrorBox error={storageError} />
            </>
          )}
          {storageBlocked && (
            <Button
              type="button"
              variant="outline"
              disabled={pending || !owns}
              onClick={read}
            >
              重新读取恢复记录
            </Button>
          )}
          {record?.phase === "editable" && (
            <Button
              type="button"
              variant="outline"
              disabled={pending || !owns}
              onClick={next}
            >
              结束已拒绝请求，按当前目标新建
            </Button>
          )}
          {(record || storageBlocked) && (
            <details>
              <summary>管理本机创建恢复记录</summary>
              <p>
                清除不会撤销服务器已创建的对象。请先核对已有记录，未核对就新建可能产生重复记录。
              </p>
              <Link href={list}>核对已有记录</Link>
              <Button
                type="button"
                variant="outline"
                disabled={pending || !owns}
                onClick={forget}
              >
                已核对，清除本机创建记录
              </Button>
            </details>
          )}
          <div className="form-actions">
            <Button
              type="button"
              variant="outline"
              onClick={() => dialog.current?.close()}
            >
              取消
            </Button>
            {record?.phase !== "accepted" && (
              <Button
                type="submit"
                disabled={pending || !owns || storageBlocked}
              >
                {pending
                  ? "保存中…"
                  : record?.phase === "unknown"
                    ? "重试原创建请求"
                    : "保存"}
              </Button>
            )}
          </div>
        </form>
      </dialog>
    </>
  );
}

export function CreationReceiptBanner({
  workspaceId,
  path,
}: {
  workspaceId: string;
  path: string;
}) {
  const cache = useQueryClient();
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    const read = () => {
      let found = false;
      for (const kind of ["project", "thread", "note"] as const) {
        try {
          const value = readCreation(workspaceId, kind);
          if (value?.phase === "accepted" && creationObjectPath(value) === path)
            found = true;
        } catch {
          /* A corrupt record is handled at its creation entry point. */
        }
      }
      setConfirmed(found);
    };
    read();
    window.addEventListener("storage", read);
    return () => window.removeEventListener("storage", read);
  }, [workspaceId, path]);
  if (!confirmed) return null;
  return (
    <section className="creation-receipt-banner" aria-label="创建确认回执">
      <p role="status">
        创建已确认。详情或后续修改以服务器读取为准，读取失败不需要重新创建。
      </p>
      <Button
        type="button"
        variant="outline"
        onClick={() => {
          void cache.invalidateQueries({
            queryKey: ["workspace", workspaceId],
          });
        }}
      >
        重读已有记录
      </Button>
    </section>
  );
}
