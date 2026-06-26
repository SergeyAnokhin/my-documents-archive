import { useState, useRef, useEffect } from "react";
import { uid } from "./labUtils";

export interface LogLine {
  id: string;
  ts: string;
  msg: string;
  kind: "info" | "ok" | "err";
}

/** Append-only activity log with auto-scroll for the OCR Lab panel. */
export function useLogs() {
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [showLogs, setShowLogs] = useState(false);
  const logsEndRef = useRef<HTMLDivElement>(null);

  const addLog = (msg: string, kind: LogLine["kind"] = "info") => {
    const ts = new Date().toLocaleTimeString("ru-RU", { hour12: false });
    setLogs(prev => [...prev, { id: uid(), ts, msg, kind }]);
  };

  const clearLogs = () => setLogs([]);

  useEffect(() => {
    if (showLogs) logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs, showLogs]);

  return { logs, showLogs, setShowLogs, addLog, clearLogs, logsEndRef };
}
