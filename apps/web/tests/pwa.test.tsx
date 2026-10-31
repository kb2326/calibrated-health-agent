import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { type Board, Scoreboard } from "@/components/Scoreboard";

const root = process.cwd(); // vitest runs in apps/web

function loadSw() {
  const listeners: Record<string, unknown> = {};
  const self = { location: { origin: "https://cha.example" }, addEventListener: (t: string, f: unknown) => { listeners[t] = f; },
                 __cacheable: undefined as undefined | ((url: string) => boolean) };
  new Function("self", "caches", readFileSync(join(root, "public", "sw.js"), "utf8"))(self, {});
  return { cacheable: self.__cacheable!, listeners };
}

describe("service worker", () => {
  it("caches only app-shell paths and never /api/*", () => {
    const { cacheable, listeners } = loadSw();
    expect(cacheable("https://cha.example/")).toBe(true);
    expect(cacheable("https://cha.example/_next/static/chunks/app.js")).toBe(true);
    expect(cacheable("https://cha.example/api/receipts/r-0123456789")).toBe(false);
    expect(cacheable("https://cha.example/api/agent")).toBe(false);
    expect(cacheable("https://cha.example/api/scoreboard")).toBe(false);
    expect(cacheable("https://elsewhere.example/")).toBe(false);
    expect(Object.keys(listeners).sort()).toEqual(["activate", "fetch", "install"]);
  });
});

describe("manifest", () => {
  it("has name, icons, standalone display and theme colour", () => {
    const m = JSON.parse(readFileSync(join(root, "public", "manifest.webmanifest"), "utf8"));
    expect(m.name).toBe("Calibrated Health Agent");
    expect(m.display).toBe("standalone");
    expect(m.theme_color).toMatch(/^#/);
    expect(m.icons.map((i: { sizes: string }) => i.sizes)).toEqual(expect.arrayContaining(["192x192", "512x512"]));
  });
});

describe("scoreboard", () => {
  const base: Board = {
    days_locked: 9, days_scored: 6,
    primary: { target: "energy", n: 6, not_yet: true },
    secondary: [],
    forecasters: [
      { id: "persistence", target: "energy", n: 6, mean_rps: 0.21, not_yet: true },
      { id: "gemini:gemini-3.5-flash-lite", target: "energy", n: 12, mean_rps: 0.18,
        skill_vs_persistence: 0.14, not_yet: false },
    ],
  };

  it('shows n beside every number and "not yet" below ten', () => {
    render(<Scoreboard board={base} />);
    expect(screen.getByText("Not yet")).toBeInTheDocument();
    expect(screen.getByText(/Scores appear after 10 paired days; 6 so far/)).toBeInTheDocument();
    expect(screen.getAllByText(/not yet · 6 of 10 days/)).toHaveLength(2);
    expect(screen.getByText("+14%")).toBeInTheDocument();
    expect(screen.getByText("Gemini")).toBeInTheDocument();
  });

  it("explains an empty board", () => {
    render(<Scoreboard board={{ ...base, forecasters: [] }} />);
    expect(screen.getByText(/No forecast has been scored yet/)).toBeInTheDocument();
  });
});
