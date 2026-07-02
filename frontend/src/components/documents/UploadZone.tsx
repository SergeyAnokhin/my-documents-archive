import { useRef, useState, type DragEvent, type ChangeEvent } from "react";
import { Upload, CheckCircle, AlertCircle, Type } from "lucide-react";
import { uploadDocument } from "../../api/documents";
import { useT } from "../../i18n";
import { Button } from "../ui/Button";
import "./UploadZone.css";

interface Props {
  onUploaded: () => void;
}

type UploadState = "idle" | "dragging" | "uploading" | "success" | "error";

// Turns an optional user-entered title into a safe .txt filename, falling
// back to a timestamp when left blank.
function textToFilename(title: string): string {
  const trimmed = title.trim();
  if (!trimmed) return `note-${Date.now()}.txt`;
  const safe = trimmed.replace(/[\\/:*?"<>|]+/g, "-").slice(0, 80);
  return safe.toLowerCase().endsWith(".txt") ? safe : `${safe}.txt`;
}

export function UploadZone({ onUploaded }: Props) {
  const { t } = useT();
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<UploadState>("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [queue, setQueue] = useState(0);
  const [done, setDone] = useState(0);
  const [showTextForm, setShowTextForm] = useState(false);
  const [textValue, setTextValue] = useState("");
  const [textTitle, setTextTitle] = useState("");

  async function processFiles(files: FileList | File[]) {
    const list = Array.from(files);
    if (!list.length) return;

    setState("uploading");
    setQueue(list.length);
    setDone(0);

    let errors = 0;
    for (const file of list) {
      try {
        await uploadDocument(file);
        setDone((d) => d + 1);
      } catch (e: unknown) {
        errors++;
        setErrorMsg(e instanceof Error ? e.message : "Upload failed");
      }
    }

    if (errors === 0) {
      setState("success");
      onUploaded();
      setTimeout(() => setState("idle"), 2500);
    } else {
      setState("error");
      setTimeout(() => setState("idle"), 3000);
    }
  }

  const onDragOver = (e: DragEvent) => { e.preventDefault(); setState("dragging"); };
  const onDragLeave = () => { if (state === "dragging") setState("idle"); };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    processFiles(e.dataTransfer.files);
  };
  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) processFiles(e.target.files);
    e.target.value = "";
  };

  const submitText = () => {
    if (!textValue.trim()) return;
    const file = new File([textValue], textToFilename(textTitle), { type: "text/plain" });
    setShowTextForm(false);
    setTextValue("");
    setTextTitle("");
    processFiles([file]);
  };

  if (state === "idle" && showTextForm) {
    return (
      <div className="upload-text-form">
        <p className="upload-zone-hint">{t.pasteTextTitle}</p>
        <input
          type="text"
          className="upload-text-form-title"
          placeholder={t.pasteTextFilenamePlaceholder}
          value={textTitle}
          onChange={(e) => setTextTitle(e.target.value)}
        />
        <textarea
          className="upload-text-form-body"
          placeholder={t.pasteTextPlaceholder}
          value={textValue}
          onChange={(e) => setTextValue(e.target.value)}
          rows={8}
          autoFocus
        />
        <div className="upload-text-form-actions">
          <Button variant="ghost" size="sm" onClick={() => setShowTextForm(false)}>
            {t.pasteTextCancel}
          </Button>
          <Button variant="primary" size="sm" onClick={submitText} disabled={!textValue.trim()}>
            {t.pasteTextSubmit}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="upload-zone-wrapper">
      <div
        className={`upload-zone upload-zone--${state}`}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => state === "idle" && inputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-label={t.uploadTitle}
        onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.jpg,.jpeg,.png,.tiff,.tif,.heic,.heif,.webp,.docx,.txt"
          multiple
          className="sr-only"
          onChange={onFileChange}
          aria-hidden="true"
        />

        {state === "idle" || state === "dragging" ? (
          <>
            <div className="upload-zone-icon">
              <Upload size={24} />
            </div>
            <p className="upload-zone-hint">{t.uploadHint}</p>
            <p className="upload-zone-accept text-xs text-muted">{t.uploadAccept}</p>
          </>
        ) : state === "uploading" ? (
          <>
            <div className="upload-zone-spinner" />
            <p className="upload-zone-hint">{t.uploading} {done}/{queue}</p>
          </>
        ) : state === "success" ? (
          <>
            <CheckCircle size={28} className="upload-zone-success-icon" />
            <p className="upload-zone-hint">{t.uploaded}</p>
          </>
        ) : (
          <>
            <AlertCircle size={28} className="upload-zone-error-icon" />
            <p className="upload-zone-hint">{errorMsg || t.error}</p>
          </>
        )}
      </div>

      {state === "idle" && (
        <button
          type="button"
          className="upload-zone-text-toggle"
          onClick={() => setShowTextForm(true)}
        >
          <Type size={12} /> {t.pasteTextLink}
        </button>
      )}
    </div>
  );
}
