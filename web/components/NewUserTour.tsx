"use client";

import { type CSSProperties, useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Bot,
  CheckCircle2,
  GraduationCap,
  LayoutGrid,
  Library,
  MessageSquareText,
  PenLine,
  Plus,
  Settings,
  X,
  type LucideIcon,
} from "lucide-react";
import { useAppShell } from "@/context/AppShellContext";
import { useAuth } from "@/context/AuthContext";
import {
  completeNewUserTour,
  shouldShowNewUserTour,
} from "@/lib/onboarding";

interface TourStep {
  targetId: string;
  title: string;
  description: string;
  icon: LucideIcon;
}

interface TourRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

interface ViewportSize {
  width: number;
  height: number;
}

const tourSteps: TourStep[] = [
  {
    targetId: "nav-new-chat",
    title: "新建对话",
    description: "有新问题时从这里开始，适合单独提问、整理思路或重新开启一轮学习。",
    icon: Plus,
  },
  {
    targetId: "nav-kaoyan",
    title: "考研助手",
    description: "这里集中学习计划、练习安排、错题复盘和阶段进度，是备考主入口。",
    icon: GraduationCap,
  },
  {
    targetId: "nav-chat",
    title: "Chat 学习对话",
    description: "把题目、概念或复盘问题发到这里，让 AI 陪你一步步讲清楚。",
    icon: MessageSquareText,
  },
  {
    targetId: "nav-agents",
    title: "TutorBot",
    description: "创建更专门的学习 Bot，用固定设定陪你刷题、讲题或长期跟进。",
    icon: Bot,
  },
  {
    targetId: "nav-co-writer",
    title: "Co-Writer",
    description: "需要写作、改稿、整理材料时，可以在这里和 AI 一起打磨文档。",
    icon: PenLine,
  },
  {
    targetId: "nav-book",
    title: "Book",
    description: "把主题生成成章节化学习内容，适合系统梳理一个完整知识块。",
    icon: Library,
  },
  {
    targetId: "nav-knowledge",
    title: "Knowledge 知识库",
    description: "上传资料、管理知识库，让后续问答能基于你的教材和笔记来回答。",
    icon: BookOpen,
  },
  {
    targetId: "nav-space",
    title: "Space 学习空间",
    description: "查看笔记、记忆、题库和技能入口，把零散内容沉淀成自己的学习资产。",
    icon: LayoutGrid,
  },
  {
    targetId: "nav-settings",
    title: "Settings",
    description: "模型、主题、接口和个人偏好都在这里调整，遇到配置问题先来这里看。",
    icon: Settings,
  },
] as const;

const SPOTLIGHT_PADDING = 7;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function readTargetRect(targetId: string): TourRect | null {
  if (typeof document === "undefined") return null;
  const target = document.querySelector<HTMLElement>(
    `[data-tour-id="${targetId}"]`,
  );
  if (!target) return null;

  const rect = target.getBoundingClientRect();
  const left = clamp(rect.left - SPOTLIGHT_PADDING, 8, window.innerWidth - 8);
  const top = clamp(rect.top - SPOTLIGHT_PADDING, 8, window.innerHeight - 8);
  const right = clamp(
    rect.right + SPOTLIGHT_PADDING,
    left + 1,
    window.innerWidth - 8,
  );
  const bottom = clamp(
    rect.bottom + SPOTLIGHT_PADDING,
    top + 1,
    window.innerHeight - 8,
  );

  return {
    top,
    left,
    width: right - left,
    height: bottom - top,
  };
}

function getGuideCardStyle(
  rect: TourRect | null,
  viewport: ViewportSize,
): CSSProperties {
  if (!rect || viewport.width < 720) {
    return {
      bottom: 16,
      left: 16,
      right: 16,
    };
  }

  const cardWidth = 390;
  const gap = 18;
  const margin = 16;
  const estimatedHeight = 300;
  let left = rect.left + rect.width + gap;
  if (left + cardWidth > viewport.width - margin) {
    left = rect.left - cardWidth - gap;
  }
  left = clamp(left, margin, viewport.width - cardWidth - margin);

  const top = clamp(
    rect.top + rect.height / 2 - estimatedHeight / 2,
    margin,
    viewport.height - estimatedHeight - margin,
  );

  return {
    top,
    left,
    width: cardWidth,
  };
}

function SpotlightOverlay({
  targetRect,
  viewport,
}: {
  targetRect: TourRect | null;
  viewport: ViewportSize;
}) {
  if (!targetRect || viewport.width <= 0 || viewport.height <= 0) {
    return (
      <div className="fixed inset-0 z-50 bg-black/35 backdrop-blur-[1px]" />
    );
  }

  const rightStart = targetRect.left + targetRect.width;
  const bottomStart = targetRect.top + targetRect.height;
  const paneClass =
    "fixed z-50 bg-black/35 backdrop-blur-[1px] transition-all duration-200";

  return (
    <>
      <div
        className={paneClass}
        style={{
          top: 0,
          left: 0,
          width: viewport.width,
          height: targetRect.top,
        }}
      />
      <div
        className={paneClass}
        style={{
          top: targetRect.top,
          left: 0,
          width: targetRect.left,
          height: targetRect.height,
        }}
      />
      <div
        className={paneClass}
        style={{
          top: targetRect.top,
          left: rightStart,
          width: viewport.width - rightStart,
          height: targetRect.height,
        }}
      />
      <div
        className={paneClass}
        style={{
          top: bottomStart,
          left: 0,
          width: viewport.width,
          height: viewport.height - bottomStart,
        }}
      />
      <div
        className="pointer-events-none fixed z-[55] rounded-xl border-2 border-[var(--primary)] transition-all duration-200"
        style={{
          top: targetRect.top,
          left: targetRect.left,
          width: targetRect.width,
          height: targetRect.height,
          boxShadow:
            "0 0 0 4px color-mix(in srgb, var(--primary) 22%, transparent), 0 18px 50px rgba(0, 0, 0, 0.28)",
        }}
      />
    </>
  );
}

export default function NewUserTour() {
  const { user } = useAuth();
  const { setSidebarCollapsed } = useAppShell();
  const [visible, setVisible] = useState(() =>
    user ? shouldShowNewUserTour(user) : false,
  );
  const [accepted, setAccepted] = useState(false);
  const [step, setStep] = useState(0);
  const [targetRect, setTargetRect] = useState<TourRect | null>(null);
  const [viewport, setViewport] = useState<ViewportSize>({
    width: 0,
    height: 0,
  });

  const currentStep = tourSteps[step];
  const StepIcon = currentStep.icon;
  const isLastStep = step === tourSteps.length - 1;

  useEffect(() => {
    if (!visible || !accepted) return undefined;

    let frame = 0;
    const updateTarget = () => {
      setViewport({
        width: window.innerWidth,
        height: window.innerHeight,
      });
      setTargetRect(readTargetRect(currentStep.targetId));
    };
    const scheduleUpdate = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(updateTarget);
    };

    scheduleUpdate();
    window.addEventListener("resize", scheduleUpdate);
    window.addEventListener("scroll", scheduleUpdate, true);

    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", scheduleUpdate);
      window.removeEventListener("scroll", scheduleUpdate, true);
    };
  }, [accepted, currentStep.targetId, visible]);

  if (!visible || !user) return null;

  const finish = () => {
    completeNewUserTour(user);
    setVisible(false);
  };

  const startTour = () => {
    setSidebarCollapsed(false);
    setStep(0);
    setAccepted(true);
  };

  if (!accepted) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6 backdrop-blur-sm">
        <section
          aria-modal="true"
          role="dialog"
          aria-labelledby="new-user-tour-title"
          className="w-full max-w-md rounded-lg border border-[var(--border)] bg-[var(--card)] p-5 text-[var(--card-foreground)] shadow-2xl animate-fade-in"
        >
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--primary)]">
                新用户引导
              </p>
              <h2 id="new-user-tour-title" className="mt-2 text-xl font-semibold">
                这里有个新手教程
              </h2>
            </div>
            <button
              type="button"
              aria-label="跳过新手教程"
              title="跳过"
              onClick={finish}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <X size={16} />
            </button>
          </div>
          <p className="text-sm leading-6 text-[var(--muted-foreground)]">
            用一分钟熟悉侧边栏入口。开始后会逐个点亮功能位置，旁边会有简短说明和下一步按钮。
          </p>
          <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={finish}
              className="inline-flex items-center justify-center rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              跳过
            </button>
            <button
              type="button"
              onClick={startTour}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] transition hover:opacity-90"
            >
              接受并开始
              <ArrowRight size={16} />
            </button>
          </div>
        </section>
      </div>
    );
  }

  return (
    <>
      <SpotlightOverlay targetRect={targetRect} viewport={viewport} />
      <section
        aria-live="polite"
        aria-label="新手教程"
        className="fixed z-[60] rounded-lg border border-[var(--border)] bg-[var(--card)] p-4 text-[var(--card-foreground)] shadow-2xl animate-fade-in"
        style={getGuideCardStyle(targetRect, viewport)}
      >
        <div className="mb-4 flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[var(--primary)]/10 text-[var(--primary)]">
            <StepIcon size={20} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs font-medium text-[var(--muted-foreground)]">
                {step + 1} / {tourSteps.length}
              </p>
              <button
                type="button"
                aria-label="关闭新手教程"
                title="关闭"
                onClick={finish}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                <X size={15} />
              </button>
            </div>
            <h3 className="mt-1 text-base font-semibold">{currentStep.title}</h3>
            <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">
              {currentStep.description}
            </p>
          </div>
        </div>
        <div className="mb-4 flex gap-1.5" aria-hidden="true">
          {tourSteps.map((item, index) => (
            <span
              key={item.targetId}
              className={`h-1.5 flex-1 rounded-full ${
                index <= step ? "bg-[var(--primary)]" : "bg-[var(--muted)]"
              }`}
            />
          ))}
        </div>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={finish}
              className="inline-flex items-center justify-center rounded-lg px-3 py-2 text-sm font-medium text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              跳过
            </button>
            {step > 0 ? (
              <button
                type="button"
                onClick={() => setStep((value) => Math.max(0, value - 1))}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                <ArrowLeft size={15} />
                上一步
              </button>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => {
              if (isLastStep) {
                finish();
                return;
              }
              setStep((value) => value + 1);
            }}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] transition hover:opacity-90"
          >
            {isLastStep ? "完成" : "下一步"}
            {isLastStep ? <CheckCircle2 size={16} /> : <ArrowRight size={16} />}
          </button>
        </div>
      </section>
    </>
  );
}
