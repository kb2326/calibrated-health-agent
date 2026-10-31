import type { Metadata, Viewport } from "next";
import { JetBrains_Mono, Saira, Saira_Condensed } from "next/font/google";
import "./globals.css";

// Self-hosted at build time: no request to Google at runtime, so the CSP stays 'self'.
const sairaCondensed = Saira_Condensed({ subsets: ["latin"], weight: ["500", "700", "800"],
                                         style: ["normal"], variable: "--font-saira-condensed" });
const saira = Saira({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-saira" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-jetbrains" });

export const metadata: Metadata = {
  title: "Calibrated Health Agent",
  description: "Ask your own health data. Every number has a receipt.",
};

export const viewport: Viewport = {
  width: "device-width", initialScale: 1, viewportFit: "cover",
  themeColor: [{ media: "(prefers-color-scheme: dark)", color: "#101317" },
               { media: "(prefers-color-scheme: light)", color: "#f4f5f7" }],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sairaCondensed.variable} ${saira.variable} ${jetbrains.variable}`}>
      <body>{children}</body>
    </html>
  );
}
