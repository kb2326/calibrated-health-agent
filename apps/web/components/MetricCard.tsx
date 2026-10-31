"use client";
import { useEffect, useState } from "react";
import { asSeries, fetchReceipt, type Series } from "@/lib/receipts";
import { ReceiptChip } from "./ReceiptChip";

const W = 560, H = 170, PAD_L = 40, PAD_B = 22, TOP = 12;

function niceTicks(lo: number, hi: number): number[] {
  const span = hi - lo || 1;
  const step = 10 ** Math.floor(Math.log10(span / 3));
  const unit = [1, 2, 5, 10].map((m) => m * step).find((s) => span / s <= 5) ?? step * 10;
  const start = Math.floor(lo / unit) * unit;
  const ticks: number[] = [];
  for (let t = start; t <= hi + unit / 2; t += unit) ticks.push(Number(t.toFixed(6)));
  return ticks;
}

function label(key: string): string {
  return key.replaceAll("_", " ");
}

/** Bars drawn to one scale from the receipt's own rows; the best value is purple. */
export function SeriesChart({ series }: { series: Series }) {
  const values = series.points.map((p) => p.value);
  const ticks = niceTicks(Math.min(0, ...values), Math.max(...values));
  const lo = ticks[0] ?? 0, hi = ticks.at(-1) ?? 1;
  const y = (v: number) => TOP + (H - PAD_B - TOP) * (1 - (v - lo) / (hi - lo || 1));
  const bw = (W - PAD_L - 8) / series.points.length;
  const max = Math.max(...values);
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" className="mt-2.5 block h-auto w-full"
      aria-label={`${label(series.key)} for ${series.points.length} days, from ${series.points[0]?.date} to ${series.points.at(-1)?.date}`}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={PAD_L} x2={W - 6} y1={y(t)} y2={y(t)} stroke="var(--c-grid)" />
          <text x={PAD_L - 6} y={y(t) + 4} textAnchor="end" fontSize="10.5" fill="var(--c-muted)" fontFamily="var(--font-mono)">{t}</text>
        </g>
      ))}
      {series.points.map((p, i) => {
        const x = PAD_L + i * bw + bw * 0.18, w = bw * 0.64;
        return (
          <g key={p.date}>
            <rect x={x} y={y(p.value)} width={w} height={Math.max(0, y(lo) - y(p.value))}
              fill={p.value === max ? "var(--c-best)" : "var(--c-bar)"} />
            {series.points.length <= 14 ? (
              <text x={x + w / 2} y={H - 6} textAnchor="middle" fontSize="10.5" fill="var(--c-muted)">{p.date.slice(5)}</text>
            ) : null}
          </g>
        );
      })}
      <line x1={PAD_L} x2={W - 6} y1={y(mean)} y2={y(mean)} stroke="var(--c-accent)" strokeWidth="1.5" strokeDasharray="5 4" />
    </svg>
  );
}

export function MetricCard({ id, onOpenReceipt }: { id: string; onOpenReceipt: (id: string) => void }) {
  const [series, setSeries] = useState<Series | null>(null);
  useEffect(() => {
    let live = true;
    fetchReceipt(id).then((r) => { if (live && r.ok) setSeries(asSeries(r.receipt.output)); });
    return () => { live = false; };
  }, [id]);
  if (!series) return null;
  const values = series.points.map((p) => p.value);
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  return (
    <figure className="rounded-tele border-t-[3px] border-best bg-card px-4 pb-3 pt-4" data-testid="metric-card">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <figcaption className="font-display text-[14px] font-semibold uppercase tracking-[.04em] text-muted">
            {label(series.key)}, average of {series.points.length} days
          </figcaption>
          <div className="font-display text-[52px] font-extrabold italic leading-none tabular-nums">
            {Number(mean.toFixed(1)).toLocaleString()}
          </div>
        </div>
        <ReceiptChip id={id} onOpen={onOpenReceipt} />
      </div>
      <SeriesChart series={series} />
    </figure>
  );
}
