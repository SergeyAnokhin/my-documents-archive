import { useEffect, useRef, useState } from "react";
import { ChevronLeft } from "lucide-react";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { useT } from "../../i18n";
import {
  createTask, runTask, listProviders, getTaskCandidates, getScopeCount, getCompressCandidates,
} from "../../api/documents";
import type { AIProvider, Task, TaskType } from "../../types";
import {
  ALL_TYPES, TYPES_WITH_LIMIT, BATCH_PROVIDER_TYPE, BATCH_POLL_DEFAULTS,
  TYPES_WITH_SCOPE, TYPES_WITH_FORCE, TASK_DOC_URLS, TASK_LABELS,
} from "./taskConfig";

export interface TaskPreCreate {
  taskType: TaskType;
  title: string;
  config: Record<string, unknown>;
  candidateCount?: number;
}

interface CreateProps {
  t: ReturnType<typeof useT>["t"];
  onCreated: (task: Task) => void;
  onClose: () => void;
  initialType?: TaskType;
  initialTitle?: string;
  initialConfig?: Record<string, unknown>;
  initialCandidateCount?: number;
}

export function CreateTaskModal({ t, onCreated, onClose, initialType, initialTitle, initialConfig, initialCandidateCount }: CreateProps) {
  const [selectedType, setSelectedType] = useState<TaskType | null>(initialType ?? null);
  const [title, setTitle] = useState(initialTitle ?? "");
  const [limit, setLimit] = useState("100");
  const [maxClusters, setMaxClusters] = useState("40");
  const [minClusters, setMinClusters] = useState("2");
  const [pollInterval, setPollInterval] = useState("30");
  const [providerId, setProviderId] = useState<string>("");
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [saving, setSaving] = useState(false);
  const [forceEmbed, setForceEmbed] = useState(false);
  const [candidates, setCandidates] = useState<Record<string, number | null> | null>(null);
  const [scope, setScope] = useState(1);
  const [scopeCount, setScopeCount] = useState<number | null>(null);
  const [scopeLoading, setScopeLoading] = useState(false);
  const [maxLongSide, setMaxLongSide] = useState("1024");
  const [compressCount, setCompressCount] = useState<{ count: number; total_images: number } | null>(null);
  const [compressLoading, setCompressLoading] = useState(false);
  const compressDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const batchProviderType = selectedType ? BATCH_PROVIDER_TYPE[selectedType] : undefined;
  const isBatch = !!batchProviderType;
  const isRecluster = selectedType === "recluster";
  const hasScope = selectedType ? TYPES_WITH_SCOPE.includes(selectedType) : false;
  const providerLabel = batchProviderType
    ? batchProviderType[0].toUpperCase() + batchProviderType.slice(1)
    : "";

  // Fetch candidate counts once on mount
  useEffect(() => {
    getTaskCandidates().then(setCandidates).catch(() => {});
  }, []);

  // Load matching providers when a batch or recluster type is selected
  useEffect(() => {
    if (!selectedType) return;
    const wanted = BATCH_PROVIDER_TYPE[selectedType];
    if (wanted) {
      listProviders()
        .then(all => {
          const matching = all.filter(p => p.provider_type === wanted && p.enabled);
          setProviders(matching);
          if (matching.length > 0) setProviderId(String(matching[0].id));
        })
        .catch(() => {});
    } else if (selectedType === "recluster") {
      listProviders()
        .then(all => {
          const matching = all.filter(
            p => (p.task_type === "analysis" || p.task_type === "both") && p.enabled,
          );
          setProviders(matching);
          if (matching.length > 0) setProviderId(String(matching[0].id));
        })
        .catch(() => {});
    }
  }, [selectedType]);

  // Fetch scope count when scope or task type changes (only for scope-aware tasks)
  useEffect(() => {
    if (!selectedType || !TYPES_WITH_SCOPE.includes(selectedType)) return;
    setScopeLoading(true);
    setScopeCount(null);
    getScopeCount(selectedType, scope)
      .then(data => setScopeCount(data.count))
      .catch(() => setScopeCount(null))
      .finally(() => setScopeLoading(false));
  }, [selectedType, scope]);

  // Fetch compress candidate count with debounce when threshold changes
  useEffect(() => {
    if (selectedType !== "compress_images") return;
    const threshold = parseInt(maxLongSide, 10);
    if (!threshold || threshold < 1) return;
    if (compressDebounceRef.current) clearTimeout(compressDebounceRef.current);
    setCompressLoading(true);
    compressDebounceRef.current = setTimeout(() => {
      getCompressCandidates(threshold)
        .then(data => setCompressCount(data))
        .catch(() => setCompressCount(null))
        .finally(() => setCompressLoading(false));
    }, 600);
    return () => {
      if (compressDebounceRef.current) clearTimeout(compressDebounceRef.current);
    };
  }, [selectedType, maxLongSide]);

  const handleSelectType = (type: TaskType) => {
    setSelectedType(type);
    setTitle(t.tasks.types[type as keyof typeof t.tasks.types] ?? type);
    setForceEmbed(false);
    setScope(1);
    setScopeCount(null);
    setMaxLongSide("1024");
    setCompressCount(null);
    const providerType = BATCH_PROVIDER_TYPE[type];
    if (providerType) {
      setLimit("100");
      setPollInterval(String(BATCH_POLL_DEFAULTS[providerType] ?? 30));
    }
    if (type === "recluster") { setMaxClusters("40"); setMinClusters("2"); }
  };

  const handleCreate = async () => {
    if (!selectedType || !title.trim()) return;
    setSaving(true);
    try {
      const config: Record<string, unknown> = { ...(initialConfig ?? {}) };
      if (TYPES_WITH_LIMIT.includes(selectedType)) {
        config.limit = parseInt(limit, 10) || 100;
      }
      if (selectedType === "recluster") {
        config.max_clusters = parseInt(maxClusters, 10) || 40;
        config.min_clusters = parseInt(minClusters, 10) || 2;
        if (providerId) config.provider_id = parseInt(providerId, 10);
      }
      if (hasScope) {
        config.scope = scope;
      }
      if (isBatch) {
        if (providerId) config.provider_id = parseInt(providerId, 10);
        config.poll_interval = parseInt(pollInterval, 10) || (batchProviderType ? BATCH_POLL_DEFAULTS[batchProviderType] : 30) || 30;
      }
      if (selectedType === "compress_images") {
        config.max_long_side = parseInt(maxLongSide, 10) || 1024;
      }
      if (TYPES_WITH_FORCE.includes(selectedType) && forceEmbed) {
        config.force = true;
      }
      const task = await createTask({ task_type: selectedType, title: title.trim(), config });
      await runTask(task.id);
      onCreated(task);
    } catch { /* ignore */ } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open onClose={onClose} title={t.tasks.selectType} size="md">
      {!selectedType ? (
        <div className="create-type-grid">
          {ALL_TYPES.map(type => (
            <button key={type} className="create-type-card" onClick={() => handleSelectType(type)}>
              <span className="task-type-label task-type-label--lg">
                {TASK_LABELS[type]}
              </span>
              <span className="create-type-name">
                {t.tasks.types[type as keyof typeof t.tasks.types]}
              </span>
              <span className="create-type-desc text-xs text-muted">
                {t.tasks.descriptions[type as keyof typeof t.tasks.descriptions]}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <div className="create-form">
          <button className="task-btn-ghost create-form-back" onClick={() => setSelectedType(null)}>
            <ChevronLeft size={14} /> {t.cancel}
          </button>

          <div className="create-form-desc">
            <p>{t.tasks.detailedDescriptions[selectedType as keyof typeof t.tasks.detailedDescriptions]}</p>
            {TASK_DOC_URLS[selectedType] && (
              <a
                className="create-form-doc-link"
                href={TASK_DOC_URLS[selectedType]}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t.tasks.readDocs}
              </a>
            )}
            {!hasScope && (
              <span className="create-form-candidates">
                {initialCandidateCount !== undefined
                  ? t.tasks.candidatesCount.replace("{{count}}", String(initialCandidateCount))
                  : candidates === null
                    ? t.tasks.candidatesLoading
                    : (() => {
                        const count = candidates[selectedType];
                        return count === null || count === undefined
                          ? t.tasks.candidatesUnknown
                          : t.tasks.candidatesCount.replace("{{count}}", String(count));
                      })()}
              </span>
            )}
          </div>

          {selectedType === "compress_images" && (
            <div className="create-form-field">
              <label className="create-form-label">{t.tasks.compressMaxSideLabel}</label>
              <input
                className="create-form-input"
                type="number"
                value={maxLongSide}
                onChange={e => setMaxLongSide(e.target.value)}
                min="100"
                max="10000"
              />
              <span className="create-form-candidates">
                {compressLoading
                  ? t.tasks.candidatesLoading
                  : compressCount === null
                    ? t.tasks.candidatesLoading
                    : t.tasks.compressCandidatesCount
                        .replace("{{count}}", String(compressCount.count))
                        .replace("{{total}}", String(compressCount.total_images))}
              </span>
            </div>
          )}

          {hasScope && (
            <div className="create-form-field">
              <label className="create-form-label">{t.tasks.scopeLabel}</label>
              <div className="create-scope-options">
                {([1, 2, 3, 4] as const).map(lvl => (
                  <label key={lvl} className={`create-scope-option${scope === lvl ? " create-scope-option--selected" : ""}`}>
                    <input
                      type="radio"
                      name="scope"
                      value={lvl}
                      checked={scope === lvl}
                      onChange={() => setScope(lvl)}
                    />
                    {t.tasks.scopeOptions[String(lvl) as keyof typeof t.tasks.scopeOptions]}
                  </label>
                ))}
              </div>
              <span className="create-form-candidates">
                {scopeLoading
                  ? t.tasks.scopeCountLoading
                  : scopeCount === null
                    ? ""
                    : t.tasks.scopeCount.replace("{{count}}", String(scopeCount))}
              </span>
            </div>
          )}

          {TYPES_WITH_FORCE.includes(selectedType) && (
            <label className="create-form-force-label">
              <input
                type="checkbox"
                checked={forceEmbed}
                onChange={e => setForceEmbed(e.target.checked)}
              />
              <span>{t.tasks.forceEmbedLabel}</span>
              <span className="create-form-force-hint text-xs text-muted">{t.tasks.forceEmbedHint}</span>
            </label>
          )}

          {selectedType === "recluster" && (
            <>
              <div className="create-form-field">
                <label className="create-form-label">{t.tasks.configMinClusters}</label>
                <input
                  className="create-form-input"
                  type="number"
                  value={minClusters}
                  onChange={e => setMinClusters(e.target.value)}
                  min="2"
                  max="100"
                />
              </div>
              <div className="create-form-field">
                <label className="create-form-label">{t.tasks.configMaxClusters}</label>
                <input
                  className="create-form-input"
                  type="number"
                  value={maxClusters}
                  onChange={e => setMaxClusters(e.target.value)}
                  min="3"
                  max="100"
                />
              </div>
            </>
          )}

          {isRecluster && (
            <div className="create-form-field">
              <label className="create-form-label">{t.tasks.configAnalysisProvider}</label>
              {providers.length === 0 ? (
                <p className="text-sm text-muted">{t.tasks.noAnalysisProvider}</p>
              ) : (
                <select
                  className="create-form-input"
                  value={providerId}
                  onChange={e => setProviderId(e.target.value)}
                >
                  {providers.map(p => (
                    <option key={p.id} value={p.id}>
                      {p.name}{p.model ? ` — ${p.model}` : ""}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}

          <div className="create-form-field">
            <label className="create-form-label">{t.tasks.taskTitle}</label>
            <input
              className="create-form-input"
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder={t.tasks.types[selectedType as keyof typeof t.tasks.types]}
            />
          </div>

          {TYPES_WITH_LIMIT.includes(selectedType) && (
            <div className="create-form-field">
              <label className="create-form-label">{t.tasks.configLimit}</label>
              <input
                className="create-form-input"
                type="number"
                value={limit}
                onChange={e => setLimit(e.target.value)}
                min="1"
                max="1000"
              />
            </div>
          )}

          {isBatch && (
            <>
              <div className="create-form-field">
                <label className="create-form-label">
                  {t.tasks.configProvider.replace("{{provider}}", providerLabel)}
                </label>
                {providers.length === 0 ? (
                  <p className="text-sm text-muted">
                    {t.tasks.noBatchProvider.replace("{{provider}}", providerLabel)}
                  </p>
                ) : (
                  <select
                    className="create-form-input"
                    value={providerId}
                    onChange={e => setProviderId(e.target.value)}
                  >
                    {providers.map(p => (
                      <option key={p.id} value={p.id}>
                        {p.name}{p.model ? ` — ${p.model}` : ""}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <div className="create-form-field">
                <label className="create-form-label">{t.tasks.configPollInterval}</label>
                <input
                  className="create-form-input"
                  type="number"
                  value={pollInterval}
                  onChange={e => setPollInterval(e.target.value)}
                  min="60"
                  max="3600"
                />
              </div>
            </>
          )}

          <div className="create-form-footer">
            <Button variant="secondary" size="sm" onClick={onClose}>{t.cancel}</Button>
            <Button
              variant="primary"
              size="sm"
              loading={saving}
              onClick={handleCreate}
              disabled={!title.trim() || (isBatch && providers.length === 0) || (isRecluster && providers.length === 0)}
            >
              {t.tasks.createTask}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
