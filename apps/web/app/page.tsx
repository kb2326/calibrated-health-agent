"use client";
import { useCallback, useEffect, useState } from "react";
import { ChatView } from "@/components/ChatView";
import { ReceiptPanel } from "@/components/ReceiptPanel";
import { useAgentRun } from "@/lib/agent";

export default function Home() {
  const agent = useAgentRun();
  const [demo, setDemo] = useState(false);
  const [openReceipt, setOpenReceipt] = useState<string | null>(null);
  const [locationOn, setLocationOn] = useState(false);
  const [locationNote, setLocationNote] = useState<string | undefined>();
  const { setLocation } = agent;

  useEffect(() => {
    fetch("/api/health").then((r) => r.json()).then((h: { demo?: boolean }) => setDemo(Boolean(h.demo)))
      .catch(() => setDemo(false));
  }, []);

  // The device location is used only for weather and only after the person opts in.
  const toggleLocation = useCallback(() => {
    if (locationOn) {
      setLocation(null);
      setLocationOn(false);
      setLocationNote("Weather uses your home location.");
      return;
    }
    if (!("geolocation" in navigator)) {
      setLocationNote("This browser can't share a location; weather uses your home location.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocation({ latitude: pos.coords.latitude, longitude: pos.coords.longitude });
        setLocationOn(true);
        setLocationNote(undefined);
      },
      () => setLocationNote("Location not shared; weather uses your home location."),
      { maximumAge: 30 * 60 * 1000, timeout: 10_000 },
    );
  }, [locationOn, setLocation]);

  return (
    <main className="mx-auto grid min-h-dvh max-w-[1280px] grid-cols-1 md:grid-cols-[minmax(0,1fr)_380px]">
      <ChatView state={agent} demo={demo} onAsk={agent.ask} onOpenReceipt={setOpenReceipt}
        locationOn={locationOn} onToggleLocation={toggleLocation} locationNote={locationNote} />
      <ReceiptPanel id={openReceipt} onClose={() => setOpenReceipt(null)}
        pending={agent.pending} onApprove={agent.approve} onDeny={agent.deny} />
    </main>
  );
}
