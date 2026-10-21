"use client";
import { useEffect, useId, useRef, useState } from "react";
import { X, Plus, ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { Button } from "./ui/button";

export function ErrorBox({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  return (
    <div className="error-box" role="alert">
      <strong>暂时无法完成操作</strong>
      <p>{error instanceof Error ? error.message : "请稍后重试"}</p>
      {retry && (
        <Button type="button" variant="outline" onClick={retry}>
          重试
        </Button>
      )}
    </div>
  );
}
export function Empty({
  title,
  text,
  action,
}: {
  title: string;
  text: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-mark">
        <Plus size={22} />
      </div>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
export function Heading({
  eyebrow,
  title,
  text,
  action,
}: {
  eyebrow: string;
  title: string;
  text: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{text}</p>
      </div>
      {action}
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status" aria-label="加载中">
      <div />
      <div />
      <div />
    </div>
  );
}
export function OpenLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <Link className="open-link" href={href}>
      {children}
      <ArrowUpRight size={15} />
    </Link>
  );
}
export type Field = {
  name: string;
  label: string;
  type?: "text" | "textarea" | "select" | "date" | "multiselect" | "email";
  options?: Record<string, string>;
  required?: boolean;
  default?: string;
};

export function FormDialog({
  title,
  trigger,
  fields,
  onSubmit,
  onFormChange,
  children,
  onOpen,
}: {
  title: string;
  trigger: React.ReactNode;
  fields: Field[];
  onSubmit: (values: Record<string, string>) => Promise<void>;
  onFormChange?: (values: Record<string, string>) => void;
  children?: React.ReactNode;
  onOpen?: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const formId = useId();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  useEffect(() => () => dialog.current?.close(), []);
  return (
    <>
      <button
        className="dialog-trigger"
        onClick={() => {
          setError(undefined);
          onOpen?.();
          dialog.current?.showModal();
        }}
      >
        {trigger}
      </button>
      <dialog ref={dialog} className="form-dialog">
        <div className="dialog-heading">
          <h2>{title}</h2>
          <Button
            variant="ghost"
            size="icon"
            aria-label="关闭"
            onClick={() => dialog.current?.close()}
          >
            <X size={20} />
          </Button>
        </div>
        <form
          onChange={(event) =>
            onFormChange?.(
              Object.fromEntries(new FormData(event.currentTarget)) as Record<
                string,
                string
              >,
            )
          }
          onSubmit={async (event) => {
            event.preventDefault();
            const form = event.currentTarget;
            setPending(true);
            setError(undefined);
            try {
              const data = new FormData(form);
              const values = Object.fromEntries(data.entries()) as Record<
                string,
                string
              >;
              fields
                .filter((field) => field.type === "multiselect")
                .forEach((field) => {
                  values[field.name] = data.getAll(field.name).join(",");
                });
              await onSubmit(values);
              dialog.current?.close();
              form.reset();
            } catch (reason) {
              setError(reason);
            } finally {
              setPending(false);
            }
          }}
        >
          {fields.map((field) => (
            <div className="field" key={field.name}>
              {field.type === "multiselect" ? (
                <span id={`${formId}-${field.name}-label`}>{field.label}</span>
              ) : (
                <label htmlFor={`${formId}-${field.name}`}>
                  {field.label}
                  {field.required !== false && (
                    <span aria-hidden="true"> *</span>
                  )}
                </label>
              )}
              {field.type === "multiselect" ? (
                <span
                  className="checkbox-options"
                  role="group"
                  aria-labelledby={`${formId}-${field.name}-label`}
                >
                  {Object.entries(field.options ?? {}).map(([value, label]) => (
                    <label key={value}>
                      <input
                        type="checkbox"
                        name={field.name}
                        value={value}
                        defaultChecked={field.default
                          ?.split(",")
                          .includes(value)}
                      />
                      {label}
                    </label>
                  ))}
                  {!Object.keys(field.options ?? {}).length && (
                    <small>当前没有可选择的记录</small>
                  )}
                </span>
              ) : field.type === "textarea" ? (
                <textarea
                  id={`${formId}-${field.name}`}
                  aria-label={field.label}
                  name={field.name}
                  required={field.required !== false}
                  defaultValue={field.default}
                  rows={4}
                />
              ) : field.type === "select" ? (
                <select
                  id={`${formId}-${field.name}`}
                  aria-label={field.label}
                  name={field.name}
                  defaultValue={field.default}
                  required={field.required !== false}
                >
                  {Object.entries(field.options ?? {}).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  id={`${formId}-${field.name}`}
                  aria-label={field.label}
                  name={field.name}
                  type={field.type ?? "text"}
                  required={field.required !== false}
                  defaultValue={field.default}
                />
              )}
            </div>
          ))}
          {Boolean(error) && <ErrorBox error={error} />}
          {children}
          <div className="form-actions">
            <Button
              type="button"
              variant="outline"
              onClick={() => dialog.current?.close()}
            >
              取消
            </Button>
            <Button disabled={pending} type="submit">
              {pending ? "保存中…" : "保存"}
            </Button>
          </div>
        </form>
      </dialog>
    </>
  );
}
