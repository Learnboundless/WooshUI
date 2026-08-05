import {
  AudioLines,
  Boxes,
  Copy,
  Disc3,
  Download,
  FolderOpen,
  Library,
  LogOut,
  Play,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import type { ProjectManifest, ViewId } from "../types";
import { ContextMenu } from "./ContextMenu";

interface SidebarProps {
  activeView: ViewId;
  project: ProjectManifest | null;
  projectPath: string;
  recent: Array<{ path: string; name: string }>;
  onView: (view: ViewId) => void;
  onOpenProject: (path?: string) => void;
  onNewProject: () => void;
  onCloseProject: () => void;
  onRemoveRecent: (path: string) => void;
  onRevealProject: (path: string) => void;
  onError: (message: string) => void;
}

const items: Array<{ id: ViewId; label: string; icon: typeof Sparkles }> = [
  { id: "generate", label: "生成音效", icon: Sparkles },
  { id: "music", label: "生成音乐", icon: Disc3 },
  { id: "studio", label: "工作台", icon: SlidersHorizontal },
  { id: "models", label: "模型", icon: Boxes },
  { id: "exports", label: "导出", icon: Download },
  { id: "settings", label: "设置", icon: Settings2 },
];

export function Sidebar({
  activeView,
  project,
  projectPath,
  recent,
  onView,
  onOpenProject,
  onNewProject,
  onCloseProject,
  onRemoveRecent,
  onRevealProject,
  onError,
}: SidebarProps) {
  const [contextMenu, setContextMenu] = useState<{
    kind: "current" | "recent";
    path: string;
    name: string;
    x: number;
    y: number;
  } | null>(null);

  function openKeyboardMenu(
    kind: "current" | "recent",
    path: string,
    name: string,
    target: HTMLElement,
  ) {
    const bounds = target.getBoundingClientRect();
    setContextMenu({ kind, path, name, x: bounds.left + 24, y: bounds.top + 24 });
  }

  async function copyProjectPath(path: string) {
    try {
      await navigator.clipboard.writeText(path);
    } catch {
      onError("项目路径复制失败");
    }
  }

  return (
    <aside className="sidebar">
      <div className="brand-row">
        <div className="brand-mark"><AudioLines size={18} /></div>
        <div><strong>Woosh Studio</strong><span>SFX workstation</span></div>
      </div>
      <nav className="primary-nav" aria-label="主导航">
        {items.map(({ id, label, icon: Icon }) => (
          <button
            className={activeView === id ? "nav-item active" : "nav-item"}
            key={id}
            onClick={() => onView(id)}
          >
            <Icon size={17} />
            <span>{label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-section">
        <div className="section-label"><span>当前项目</span><Library size={14} /></div>
        {project ? (
          <button
            className="project-summary"
            onClick={() => onView("generate")}
            onContextMenu={(event) => {
              event.preventDefault();
              setContextMenu({ kind: "current", path: projectPath, name: project.name, x: event.clientX, y: event.clientY });
            }}
            onKeyDown={(event) => {
              if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
                event.preventDefault();
                openKeyboardMenu("current", projectPath, project.name, event.currentTarget);
              }
            }}
          >
            <FolderOpen size={17} />
            <span><strong>{project.name}</strong><small>{project.assets.length} 个素材</small></span>
          </button>
        ) : <div className="sidebar-empty">未打开项目</div>}
      </div>
      <div className="sidebar-section recent-list">
        <div className="section-label"><span>最近</span></div>
        {recent.slice(0, 4).map((item) => (
          <button
            key={item.path}
            onClick={() => onOpenProject(item.path)}
            title={item.path}
            onContextMenu={(event) => {
              event.preventDefault();
              setContextMenu({ kind: "recent", path: item.path, name: item.name, x: event.clientX, y: event.clientY });
            }}
            onKeyDown={(event) => {
              if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
                event.preventDefault();
                openKeyboardMenu("recent", item.path, item.name, event.currentTarget);
              }
            }}
          >
            <span>{item.name}</span>
          </button>
        ))}
      </div>
      <div className="sidebar-actions">
        <button className="secondary-button" onClick={onNewProject}><Sparkles size={15} />新建项目</button>
        <button className="icon-button" title="打开项目" onClick={() => onOpenProject()}><FolderOpen size={17} /></button>
      </div>
      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          label={`${contextMenu.name} 项目操作`}
          onClose={() => setContextMenu(null)}
          items={[
            {
              id: "open",
              label: contextMenu.kind === "current" ? "打开项目主页" : "打开项目",
              icon: <Play size={15} />,
              onSelect: () => contextMenu.kind === "current"
                ? onView("generate")
                : onOpenProject(contextMenu.path),
            },
            {
              id: "reveal",
              label: "在资源管理器中显示",
              icon: <FolderOpen size={15} />,
              onSelect: () => onRevealProject(contextMenu.path),
            },
            {
              id: "copy-path",
              label: "复制项目路径",
              icon: <Copy size={15} />,
              onSelect: () => copyProjectPath(contextMenu.path),
            },
            contextMenu.kind === "current"
              ? {
                  id: "close",
                  label: "关闭当前项目",
                  icon: <LogOut size={15} />,
                  separatorBefore: true,
                  onSelect: onCloseProject,
                }
              : {
                  id: "remove-recent",
                  label: "从最近列表移除",
                  icon: <Trash2 size={15} />,
                  destructive: true,
                  separatorBefore: true,
                  onSelect: () => onRemoveRecent(contextMenu.path),
                },
          ]}
        />
      )}
    </aside>
  );
}
