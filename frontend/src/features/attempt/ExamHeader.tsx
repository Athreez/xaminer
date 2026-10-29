import {
  CircleAlert,
  Clock,
  CloudCheck,
  CloudOff,
  LoaderCircle,
  Wifi,
  WifiOff,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import { formatClock, timeAnnouncement, timerLevel, type Connection } from "./lib";
import type { Status } from "./sync/uploader";

/**
 * The exam header (FRONTEND_SPEC § 6.1, § 6.3): title, timer, save status and connection, always
 * visible and always in words, not icons alone. Proctoring joins in E11.
 */
export function ExamHeader({
  title,
  secondsLeft,
  save,
  connection,
}: {
  title: string;
  secondsLeft: number;
  save: Status;
  connection: Connection;
}) {
  return (
    <header className="bg-card flex flex-wrap items-center gap-x-6 gap-y-2 border-b px-5 py-3">
      <h1 className="mr-auto truncate text-base font-semibold">{title}</h1>
      <Timer secondsLeft={secondsLeft} />
      <SaveStatus save={save} />
      <ConnectionStatus connection={connection} />
    </header>
  );
}

function Timer({ secondsLeft }: { secondsLeft: number }) {
  const level = timerLevel(secondsLeft);
  const [said, setSaid] = useState("");
  const before = useRef(secondsLeft);
  useEffect(() => {
    const text = timeAnnouncement(before.current, secondsLeft);
    before.current = secondsLeft;
    if (text) setSaid(text);
  }, [secondsLeft]);

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-sm font-semibold tabular-nums",
        level === "warning" && "bg-warning-soft text-warning",
        level === "danger" && "bg-danger-soft text-destructive",
      )}
    >
      <Clock className="size-4" aria-hidden />
      {/* Read on demand; announced only at set points through the live region below. */}
      <span role="timer" aria-label={`Time left ${formatClock(secondsLeft)}`}>
        {formatClock(secondsLeft)}
      </span>
      <span className="sr-only" aria-live="polite">
        {said}
      </span>
    </div>
  );
}

function answers(n: number): string {
  return `${n} ${n === 1 ? "answer" : "answers"}`;
}

/** The words for a save status (§ 6.3). */
function saveText(save: Status): string {
  switch (save.state) {
    case "saved":
      return "All saved";
    case "saving":
      return "Saving…";
    case "offline":
      return `Offline — ${answers(save.unsent)} saved on this device`;
    case "failing":
      return `${answers(save.unsent)} not saved`;
  }
}

function SaveStatus({ save }: { save: Status }) {
  const Icon =
    save.state === "saved" ? CloudCheck : save.state === "saving" ? LoaderCircle : CloudOff;
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 text-sm",
        save.state === "saved" && "text-success",
        save.state === "offline" && "text-warning",
        save.state === "failing" && "text-destructive font-semibold",
      )}
      aria-live="polite"
    >
      <Icon
        className={cn("size-4", save.state === "saving" && "motion-safe:animate-spin")}
        aria-hidden
      />
      <span>{saveText(save)}</span>
      {save.refused > 0 && (
        <span className="text-destructive flex items-center gap-1 font-semibold">
          <CircleAlert className="size-4" aria-hidden />
          {answers(save.refused)} not accepted
        </span>
      )}
    </div>
  );
}

const connectionText: Record<Connection, string> = {
  online: "Online",
  reconnecting: "Reconnecting…",
  offline: "Offline",
};

function ConnectionStatus({ connection }: { connection: Connection }) {
  const Icon = connection === "online" ? Wifi : WifiOff;
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 text-sm",
        connection === "online" ? "text-muted-foreground" : "text-warning font-medium",
      )}
      aria-live="polite"
    >
      <Icon className="size-4" aria-hidden />
      {connectionText[connection]}
    </div>
  );
}
