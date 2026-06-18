import { useRef, useState, type DragEvent, type ChangeEvent } from "react";
import { Upload, CheckCircle, AlertCircle } from "lucide-react";
import { uploadDocument } from "../../api/documents";
import { useT } from "../../i18n";
import "./UploadZone.css";

interface Props {
  onUploaded: () => void;
}

type UploadState = "idle" | "dragging" | "uploading" | "success" | "error";

export function UploadZone({ onUploaded }: Props) {
  const { t } = useT();
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<UploadState>("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [queue, setQueue] = useState(0);
  const [done, setDone] = useState(0);

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

  return (
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
        accept=".pdf,.jpg,.jpeg,.png,.tiff,.tif,.heic,.heif,.webp"
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
  );
}
