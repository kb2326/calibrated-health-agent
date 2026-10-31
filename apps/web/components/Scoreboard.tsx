// The forecast scoreboard: the same rounded aggregates the public log shows. Every number
// carries its n, and anything below 10 paired days says "not yet" instead of a score.

export interface BoardRow {
  id?: string;
  forecaster?: string;
  target: string;
  n: number;
  mean_rps?: number;
  skill_vs_persistence?: number | null;
  skill_vs_reference?: number | null;
  reference?: string;
  not_yet: boolean;
}

export interface Board {
  days_locked: number;
  days_scored: number;
  primary: BoardRow;
  secondary: BoardRow[];
  forecasters: BoardRow[];
}

const NAMES: Record<string, string> = {
  climatology: "Climatology", persistence: "Same as yesterday", seasonal_naive: "Same weekday last week",
  statistical: "Statistical model", timesfm: "TimesFM",
};

export function forecasterName(id: string): string {
  if (NAMES[id]) return NAMES[id];
  if (id.startsWith("gemini") && id.includes("notes")) return "Gemini + hypotheses";
  if (id.startsWith("gemini")) return "Gemini";
  return id;
}

function skill(v: number | null | undefined): string {
  if (v == null) return "–";
  const pct = Math.round(v * 100);
  return `${pct > 0 ? "+" : ""}${pct}%`;
}

function NotYet({ n }: { n: number }) {
  return <span className="font-mono text-[12.5px] text-muted">not yet · {n} of 10 days</span>;
}

export function Scoreboard({ board }: { board: Board }) {
  const p = board.primary;
  return (
    <div className="grid gap-6">
      <section className="rounded-tele border-t-[3px] border-best bg-card p-5">
        <h2 className="font-display text-[15px] font-semibold uppercase tracking-[.04em] text-muted">
          Does the agent beat &quot;same as yesterday&quot; at predicting evening {p.target}?
        </h2>
        <div className="mt-2 font-display text-[56px] font-extrabold italic leading-none tabular-nums">
          {p.not_yet ? "Not yet" : skill(p.skill_vs_persistence)}
        </div>
        <p className="mt-2 text-[14px] text-muted">
          {p.not_yet
            ? `Scores appear after 10 paired days; ${p.n} so far.`
            : `Skill against persistence over ${p.n} paired days (positive means the agent was better).`}
        </p>
        <p className="mt-1 font-mono text-[12.5px] text-muted">{board.days_locked} days locked · {board.days_scored} scored</p>
      </section>
      <section>
        <h2 className="mb-2 font-display text-[20px] font-bold uppercase italic">All forecasters</h2>
        {board.forecasters.length === 0 ? (
          <p className="text-[14px] text-muted">No forecast has been scored yet. The first scores appear the evening after a journal entry.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[14px] tabular-nums">
              <thead>
                <tr className="text-left font-mono text-[11.5px] text-muted">
                  <th className="py-2 pr-4 font-medium">Forecaster</th><th className="py-2 pr-4 font-medium">Target</th>
                  <th className="py-2 pr-4 font-medium">n</th><th className="py-2 pr-4 font-medium">Mean RPS</th>
                  <th className="py-2 font-medium">vs same as yesterday</th>
                </tr>
              </thead>
              <tbody>
                {board.forecasters.map((r) => (
                  <tr key={`${r.id}-${r.target}`} className="border-t border-line">
                    <td className="py-2 pr-4">{forecasterName(r.id ?? "")}</td>
                    <td className="py-2 pr-4">{r.target}</td>
                    <td className="py-2 pr-4 font-mono">{r.n}</td>
                    <td className="py-2 pr-4 font-mono">{r.not_yet ? <NotYet n={r.n} /> : r.mean_rps?.toFixed(2)}</td>
                    <td className="py-2 font-mono">{r.not_yet ? <NotYet n={r.n} /> : skill(r.skill_vs_persistence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
