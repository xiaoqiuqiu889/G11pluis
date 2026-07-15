// =============================================================================
// 革命街没有尽头 · 旁观者镜头
// -----------------------------------------------------------------------------
// 决策 2：旁观者 = 镜头。
// 实现：拖动、缩放、焦点切换（不破坏电影感、不显示数值）。
// 移动端：双指缩放、单指拖动；桌面：滚轮缩放、拖动。
// 可访问性：键盘 Tab 切换焦点，方向键微调。
// ============================================================================

import { useEffect, useRef, useState, useCallback, useImperativeHandle, forwardRef } from "react";

export type FocusId = string;

export interface CameraFocus {
  id: FocusId;
  label: string;
  /** 0-100 中心点（横向） */
  x: number;
  /** 0-100 中心点（纵向） */
  y: number;
  /** 缩放建议 1-2.4 */
  zoom: number;
}

export interface ObserverCameraHandle {
  panTo: (focus: CameraFocus) => void;
  reset: () => void;
}

export interface ObserverCameraProps {
  focuses: CameraFocus[];
  defaultFocusId?: FocusId;
  children: React.ReactNode;
  ariaLabel?: string;
  className?: string;
  onFocusChange?: (id: FocusId) => void;
}

export const ObserverCamera = forwardRef<ObserverCameraHandle, ObserverCameraProps>(function ObserverCamera(
  { focuses, defaultFocusId, children, ariaLabel = "场景镜头", className = "", onFocusChange },
  ref,
) {
  const [active, setActive] = useState<FocusId>(defaultFocusId ?? focuses[0]?.id ?? "");
  const focus = focuses.find((f) => f.id === active) ?? focuses[0];

  // 拖动 / 缩放状态
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const dragRef = useRef<{ startX: number; startY: number; baseX: number; baseY: number } | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const reset = useCallback(() => {
    setPan({ x: 0, y: 0 });
    setZoom(1);
    if (focus) {
      onFocusChange?.(focus.id);
    }
  }, [focus, onFocusChange]);

  const panTo = useCallback(
    (f: CameraFocus) => {
      // 把容器中心点移到 f.x, f.y，再缩放到 f.zoom
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const targetX = (rect.width * f.x) / 100 - rect.width / 2;
      const targetY = (rect.height * f.y) / 100 - rect.height / 2;
      setPan({ x: -targetX, y: -targetY });
      setZoom(f.zoom);
      setActive(f.id);
      onFocusChange?.(f.id);
    },
    [onFocusChange],
  );

  useImperativeHandle(
    ref,
    () => ({
      panTo,
      reset,
    }),
    [panTo, reset],
  );

  // 鼠标拖动
  const onMouseDown = (e: React.MouseEvent) => {
    dragRef.current = { startX: e.clientX, startY: e.clientY, baseX: pan.x, baseY: pan.y };
  };
  const onMouseMove = (e: React.MouseEvent) => {
    if (!dragRef.current) return;
    const dx = e.clientX - dragRef.current.startX;
    const dy = e.clientY - dragRef.current.startY;
    setPan({ x: dragRef.current.baseX + dx, y: dragRef.current.baseY + dy });
  };
  const onMouseUp = () => {
    dragRef.current = null;
  };

  // 触摸
  const lastTouch = useRef<{ x: number; y: number; dist: number; baseZoom: number } | null>(null);
  const onTouchStart = (e: React.TouchEvent) => {
    if (e.touches.length === 1) {
      lastTouch.current = {
        x: e.touches[0].clientX,
        y: e.touches[0].clientY,
        dist: 0,
        baseZoom: zoom,
      };
    } else if (e.touches.length === 2) {
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      lastTouch.current = {
        x: 0,
        y: 0,
        dist: Math.hypot(dx, dy),
        baseZoom: zoom,
      };
    }
  };
  const onTouchMove = (e: React.TouchEvent) => {
    if (!lastTouch.current) return;
    if (e.touches.length === 1) {
      const dx = e.touches[0].clientX - lastTouch.current.x;
      const dy = e.touches[0].clientY - lastTouch.current.y;
      setPan((p) => ({ x: p.x + dx, y: p.y + dy }));
      lastTouch.current.x = e.touches[0].clientX;
      lastTouch.current.y = e.touches[0].clientY;
    } else if (e.touches.length === 2) {
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      const dist = Math.hypot(dx, dy);
      const factor = dist / Math.max(1, lastTouch.current.dist);
      setZoom(Math.max(1, Math.min(2.4, lastTouch.current.baseZoom * factor)));
    }
  };
  const onTouchEnd = () => {
    lastTouch.current = null;
  };

  // 滚轮缩放
  const onWheel = (e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey || Math.abs(e.deltaY) > 0) {
      const delta = -e.deltaY * 0.0015;
      setZoom((z) => Math.max(1, Math.min(2.4, z + delta)));
    }
  };

  // 键盘
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!containerRef.current?.contains(document.activeElement)) return;
      const step = 24;
      if (e.key === "ArrowLeft") setPan((p) => ({ ...p, x: p.x + step }));
      else if (e.key === "ArrowRight") setPan((p) => ({ ...p, x: p.x - step }));
      else if (e.key === "ArrowUp") setPan((p) => ({ ...p, y: p.y + step }));
      else if (e.key === "ArrowDown") setPan((p) => ({ ...p, y: p.y - step }));
      else if (e.key === "+" || e.key === "=") setZoom((z) => Math.min(2.4, z + 0.1));
      else if (e.key === "-") setZoom((z) => Math.max(1, z - 0.1));
      else if (e.key === "0") reset();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [reset]);

  return (
    <div className={`relative w-full h-full overflow-hidden bg-transparent select-none ${className}`}>
      {/* 镜头区：可拖动 */}
      <div
        ref={containerRef}
        className="absolute inset-0 cursor-grab active:cursor-grabbing focus:outline-none"
        tabIndex={0}
        role="application"
        aria-label={ariaLabel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        onWheel={onWheel}
      >
        <div
          className="absolute inset-0 transition-transform duration-500 ease-out"
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: "center center",
          }}
        >
          {children}
        </div>
      </div>

      {/* 焦点切换：底部小芯片（电影感 UI） */}
      <div
        className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-1 glass rounded-full px-2 py-1.5 z-10"
        role="tablist"
        aria-label="镜头焦点"
      >
        {focuses.map((f) => (
          <button
            key={f.id}
            role="tab"
            aria-selected={f.id === active}
            tabIndex={0}
            onClick={() => panTo(f)}
            className={`px-3 py-1 text-xs rounded-full transition-colors min-w-[60px] min-h-[32px] ${
              f.id === active
                ? "bg-amber-glow/20 text-amber-glow border border-amber-glow/40"
                : "text-paper-200/60 hover:text-paper-100 border border-transparent"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* 缩放指示（描述性，不是数值） */}
      <div className="absolute top-3 right-3 t-meta text-paper-100/40" aria-hidden>
        镜头 · {zoom === 1 ? "中景" : zoom > 1.6 ? "近景" : "稍近"}
      </div>
    </div>
  );
});
