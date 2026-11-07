"use client";

import type { ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

export type Tone = "green" | "yellow" | "red" | "blue" | "grey" | "purple";

export function statusTone(status: string): Tone {
  const normalized = status.toLowerCase();
  if (
    normalized.includes("complete") ||
    normalized.includes("received") ||
    normalized.includes("paid") ||
    normalized.includes("pass") ||
    normalized.includes("active") ||
    normalized.includes("track") ||
    normalized.includes("healthy") ||
    normalized.includes("approved")
  ) {
    return "green";
  }
  if (
    normalized.includes("risk") ||
    normalized.includes("rework") ||
    normalized.includes("partial") ||
    normalized.includes("low") ||
    normalized.includes("review") ||
    normalized.includes("accruing")
  ) {
    return "yellow";
  }
  if (
    normalized.includes("delay") ||
    normalized.includes("blocked") ||
    normalized.includes("failed") ||
    normalized.includes("critical") ||
    normalized.includes("overdue") ||
    normalized.includes("rejected")
  ) {
    return "red";
  }
  if (
    normalized.includes("approval") ||
    normalized.includes("waiting") ||
    normalized.includes("pending") ||
    normalized.includes("submitted")
  ) {
    return "blue";
  }
  if (normalized.includes("progress") || normalized.includes("sampling")) {
    return "purple";
  }
  return "grey";
}

export function Badge({ children, tone }: { children: ReactNode; tone?: Tone }) {
  const value = typeof children === "string" ? children : "";
  return <span className={`badge badge-${tone ?? statusTone(value)}`}>{children}</span>;
}

export function ProgressBar({ value, tone = "green" }: { value: number; tone?: Tone }) {
  const safeValue = Math.min(100, Math.max(0, value));
  return (
    <div className="progress-track" aria-label={`${safeValue}% complete`}>
      <span className={`progress-fill progress-${tone}`} style={{ width: `${safeValue}%` }} />
    </div>
  );
}

export function Panel({
  children,
  className = "",
  title,
  description,
  action,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || description || action) && (
        <div className="panel-heading">
          <div>
            {title && <h2>{title}</h2>}
            {description && <p>{description}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function StatCard({
  label,
  value,
  detail,
  trend,
  trendDirection = "flat",
  icon,
  emphasis,
}: {
  label: string;
  value: string;
  detail?: string;
  trend?: string;
  trendDirection?: "up" | "down" | "flat";
  icon?: ReactNode;
  emphasis?: Tone;
}) {
  const TrendIcon = trendDirection === "up" ? ArrowUpRight : trendDirection === "down" ? ArrowDownRight : Minus;
  return (
    <article className={`stat-card ${emphasis ? `stat-${emphasis}` : ""}`}>
      <div className="stat-topline">
        <span>{label}</span>
        {icon && <span className="stat-icon">{icon}</span>}
      </div>
      <strong>{value}</strong>
      <div className="stat-meta">
        {trend && (
          <span className={`trend trend-${trendDirection}`}>
            <TrendIcon size={13} /> {trend}
          </span>
        )}
        {detail && <span>{detail}</span>}
      </div>
    </article>
  );
}

export function Avatar({ name, small = false }: { name: string; small?: boolean }) {
  const initials = name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
  return <span className={`avatar ${small ? "avatar-small" : ""}`}>{initials}</span>;
}

export function Metric({ label, value, accent }: { label: string; value: ReactNode; accent?: boolean }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={accent ? "accent-text" : ""}>{value}</strong>
    </div>
  );
}

export function TableWrap({ children }: { children: ReactNode }) {
  return <div className="table-wrap">{children}</div>;
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <span>HBA</span>
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}
