"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  ChevronDown,
  CircleHelp,
  FileText,
  GitBranch,
  LayoutDashboard,
  LogOut,
  Search,
  Settings,
  Sparkles,
  SquareCheck,
  Waypoints,
  History,
} from "lucide-react";
import { api, ApiError, write } from "@/lib/api";
import { scopedKey } from "@/lib/query-client";
import type { Project, User } from "@/lib/types";
import { AuthScreen } from "./auth-screen";
import { ErrorBox, Loading } from "./common";
import { ResearchPages } from "./research-pages";
import { CreationReceiptBanner } from "./research-create-dialog";
import { usePagedRows } from "@/lib/pagination";

const navigation = [
  ["/dashboard", "我的科研桌面", LayoutDashboard],
  ["/projects", "研究课题", Waypoints],
  ["/library", "文献库", BookOpen],
  ["/notes", "科研笔记", FileText],
  ["/tasks", "下一步行动", SquareCheck],
  ["/activity", "研究日志", History],
] as const;

export function WorkspaceApp() {
  const path = usePathname();
  const router = useRouter();
  const cache = useQueryClient();
  const [selected, setSelected] = useState("");
  const [search, setSearch] = useState("");
  const identity = useQuery({
    queryKey: ["identity"],
    queryFn: () => api<User>("/me"),
    retry: false,
  });
  const user = identity.data?.data;
  const projects = usePagedRows<Project>({
    queryKey: scopedKey(user?.workspace_id ?? "", "projects"),
    path: "/projects",
    enabled: !!user,
  });
  const preferred = useQuery({
    queryKey: scopedKey(user?.workspace_id ?? "", "current-project"),
    queryFn: () => api<Project | null>("/projects/current"),
    enabled: !!user,
  });
  const current =
    projects.data?.data.find(
      (item) => item.id === selected && item.status !== "archived",
    ) ??
    preferred.data?.data ??
    projects.data?.data.find((item) => item.status !== "archived");
  useEffect(() => {
    if (
      path !== "/login" &&
      identity.error instanceof ApiError &&
      identity.error.status === 401
    )
      router.replace("/login");
  }, [identity.error, path, router]);
  if (path === "/login") return <AuthScreen />;
  if (identity.isPending)
    return (
      <div className="initial-loading">
        <Loading />
      </div>
    );
  if (identity.error)
    return identity.error instanceof ApiError &&
      identity.error.status === 401 ? null : (
      <ErrorBox error={identity.error} retry={() => identity.refetch()} />
    );
  if (!user) return null;
  if (projects.isPending || preferred.isPending) return <Loading />;
  if (projects.error || (preferred.error && !preferred.data))
    return (
      <ErrorBox
        error={projects.error ?? preferred.error}
        retry={() => {
          projects.refetch();
          preferred.refetch();
        }}
      />
    );
  const options = [
    ...new Map(
      [...(current ? [current] : []), ...projects.data.data].map((item) => [
        item.id,
        item,
      ]),
    ).values(),
  ];
  return (
    <div className="workspace">
      <aside className="sidebar">
        <Link href="/dashboard" className="brand">
          <div className="brand-symbol">
            <GitBranch size={23} />
          </div>
          <div>
            ResearchOS<small>我的科研空间</small>
          </div>
        </Link>
        <div className="nav-label">研究工作台</div>
        <nav>
          {navigation.map(([href, label, Icon]) => (
            <Link
              className={path.startsWith(href) ? "nav-item active" : "nav-item"}
              href={href}
              key={href}
            >
              <Icon size={19} />
              {label}
              {href === "/projects" && (
                <span className="nav-count">
                  {projects.data.data.length}
                  {projects.hasNextPage ? "+" : ""}
                </span>
              )}
            </Link>
          ))}
        </nav>
        <div className="sidebar-note">
          <Sparkles size={18} />
          <strong>从一个好问题开始</strong>
          <p>把证据与判断留下，让下一步研究更清楚。</p>
        </div>
        <div className="sidebar-bottom">
          <Link href="/profile/research" className="nav-item">
            <CircleHelp size={18} />
            科研画像
          </Link>
          <Link href="/settings/data" className="nav-item">
            <Settings size={18} />
            设置与数据
          </Link>
          <div className="account">
            <div className="avatar">{user.display_name.slice(0, 1)}</div>
            <div>
              <strong>{user.display_name}</strong>
              <small>个人私有空间</small>
            </div>
            <button
              aria-label="退出登录"
              onClick={async () => {
                await write("/auth/logout", "POST", {});
                Object.keys(localStorage)
                  .filter(
                    (key) =>
                      key.startsWith(
                        `researchos:draft:${user.workspace_id}:`,
                      ) || key.startsWith(`researchos.${user.workspace_id}.`),
                  )
                  .forEach((key) => localStorage.removeItem(key));
                cache.clear();
                setSelected("");
                router.replace("/login");
              }}
            >
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="topbar">
          <div className="project-selector">
            <span>当前课题</span>
            <select
              aria-label="切换当前课题"
              value={current?.id ?? ""}
              onChange={(event) => setSelected(event.target.value)}
            >
              {!current && <option value="">尚未创建课题</option>}
              {options
                .filter((item) => item.status !== "archived")
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
            </select>
            <ChevronDown size={14} />
          </div>
          {projects.hasNextPage && (
            <button
              className="text-button"
              aria-label="更多课题选项"
              disabled={projects.isFetching}
              onClick={() => projects.fetchNextPage({ cancelRefetch: false })}
            >
              更多课题
            </button>
          )}
          {Boolean(projects.pageError) && (
            <ErrorBox
              error={projects.pageError}
              retry={() => projects.fetchNextPage()}
            />
          )}
          <form
            className="global-search"
            onSubmit={(event) => {
              event.preventDefault();
              if (search.trim())
                router.push(`/search?q=${encodeURIComponent(search.trim())}`);
            }}
          >
            <Search size={17} />
            <input
              aria-label="搜索研究资料"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索研究问题、文献与笔记"
            />
            <kbd>↵</kbd>
          </form>
          <div className="private-label">
            <span />
            私有空间
          </div>
        </header>
        <main className="content">
          <CreationReceiptBanner workspaceId={user.workspace_id} path={path} />
          {preferred.error && preferred.data && (
            <ErrorBox
              error={preferred.error}
              retry={() => {
                void preferred.refetch();
              }}
            />
          )}
          <ResearchPages
            path={path}
            user={user}
            current={current}
            projects={projects.data?.data ?? []}
            projectPaging={projects}
          />
        </main>
        <footer className="workspace-footer">
          ResearchOS · 每个研究判断，都能回到它的依据。
        </footer>
      </div>
    </div>
  );
}
