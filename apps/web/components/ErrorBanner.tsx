import type { UiError } from "@/lib/types";

// Plain words for what went wrong and what to do next.
export function friendlyError(error: UiError): string {
  if (error.code === "BUDGET") return error.message;
  if (/quota|rate limit|resource.?exhausted|429/i.test(error.message))
    return "The model is busy right now (rate limit). Wait a minute and ask again.";
  return error.message;
}

export function ErrorBanner({ error }: { error: UiError }) {
  return (
    <div role="alert" className="rounded-tele border-l-[3px] border-bad bg-soft px-3.5 py-2.5 text-[14px]">
      {friendlyError(error)}
    </div>
  );
}
