import './i18n'
import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Upload, Search, Grid3X3, List, Download, X, FileText, Menu, Layers, AlertCircle, CheckCircle, Clock } from 'lucide-react'

// ── Types ─────────────────────────────────────────────────

interface Document {
  id: string
  original_filename: string
  file_size: number
  mime_type: string
  doc_date: string | null
  doc_type: string
  tags: string[]
  summary: string
  ocr_text: string
  ocr_status: string | null
  thumbnail_path: string
  created_at: string | null
  page_count: number
}

interface SearchResult {
  id: string
  original_filename: string
  ocr_text: string
  summary: string
  tags: string
  snippet: string
}

interface Stats { total: number; indexed: number; pending: number; errors: number }

// ── Helpers ───────────────────────────────────────────────

function fmtSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

const OCR_STATUS_ICON: Record<string, { icon: typeof CheckCircle; cls: string; label: Record<string, string> }> = {
  done: { icon: CheckCircle, cls: 'text-green-400', label: { ru: 'OCR готов', en: 'OCR done' } },
  pending: { icon: Clock, cls: 'text-[#666]', label: { ru: 'Ожидает OCR', en: 'OCR pending' } },
  error: { icon: AlertCircle, cls: 'text-red-400', label: { ru: 'Ошибка OCR', en: 'OCR error' } },
  skipped: { icon: Clock, cls: 'text-[#555]', label: { ru: 'Пропущено', en: 'Skipped' } },
}

// ── App ───────────────────────────────────────────────────

export default function App() {
  const { t, i18n } = useTranslation()
  const [docs, setDocs] = useState<Document[]>([])
  const [stats, setStats] = useState<Stats>({ total: 0, indexed: 0, pending: 0, errors: 0 })
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null)
  const [view, setView] = useState<'grid' | 'list'>('grid')
  const [selected, setSelected] = useState<Document | null>(null)
  const [sideOpen, setSideOpen] = useState(false)
  const [dropActive, setDropActive] = useState(false)
  const [uploading, setUploading] = useState<string[]>([])
  const fileRef = useRef<HTMLInputElement>(null)

  const lang = i18n.language.startsWith('ru') ? 'ru' : 'en'

  // ── Fetch ───────────────────────────────────────────────

  const fetchDocs = useCallback(async () => {
    const [dRes, sRes] = await Promise.all([
      fetch('/api/documents?limit=200'),
      fetch('/api/stats'),
    ])
    if (dRes.ok) {
      const data = await dRes.json()
      setDocs(data.documents || [])
    }
    if (sRes.ok) {
      const s = await sRes.json()
      setStats(s)
    }
    setLoading(false)
  }, [])

  useEffect(() => { fetchDocs() }, [fetchDocs])

  // ── Search (API full-text) ──────────────────────────────

  useEffect(() => {
    if (!search.trim()) {
      setSearchResults(null)
      return
    }
    const id = setTimeout(async () => {
      try {
        const params = new URLSearchParams({ q: search.trim(), limit: '50' })
        const res = await fetch(`/api/search?${params}`)
        if (res.ok) {
          const data = await res.json()
          setSearchResults(data.results || [])
        }
      } catch {}
    }, 300)
    return () => clearTimeout(id)
  }, [search])

  const hasSearchResults = searchResults !== null

  // ── Upload ──────────────────────────────────────────────

  async function uploadFiles(files: FileList | File[]) {
    const arr = Array.from(files)
    if (arr.length === 0) return
    setUploading(prev => [...prev, ...arr.map(f => f.name)])
    for (const f of arr) {
      const fd = new FormData()
      fd.append('file', f)
      try {
        await fetch('/api/documents/upload', { method: 'POST', body: fd })
      } catch {}
    }
    setUploading([])
    fetchDocs()
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDropActive(false)
    uploadFiles(e.dataTransfer.files)
  }, [])

  const onFilePick = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) uploadFiles(e.target.files)
  }, [])

  // ── Filter (client-side fallback) ───────────────────────

  const filtered = hasSearchResults
    ? docs.filter(d => searchResults!.some(r => r.id === d.id))
    : search
      ? docs.filter(d =>
          d.original_filename.toLowerCase().includes(search.toLowerCase()) ||
          (d.ocr_text?.toLowerCase() || '').includes(search.toLowerCase()) ||
          (d.summary?.toLowerCase() || '').includes(search.toLowerCase()) ||
          (d.tags || []).some((t: string) => t.toLowerCase().includes(search.toLowerCase()))
        )
      : docs

  const isUploading = uploading.length > 0

  // ── Thumbnail helper ────────────────────────────────────

  function thumbUrl(doc: Document): string | null {
    return doc.thumbnail_path ? `/api/documents/${doc.id}/thumbnail` : null
  }

  // ── OCR Status Badge ────────────────────────────────────

  function OcrBadge({ status }: { status: string | null }) {
    const info = OCR_STATUS_ICON[status || ''] || OCR_STATUS_ICON.pending
    const Icon = info.icon
    return (
      <span className={`inline-flex items-center gap-1 text-[10px] ${info.cls}`}>
        <Icon size={10} />
        {info.label[lang as keyof typeof info.label] || status}
      </span>
    )
  }

  // ── Snippet highlighter ─────────────────────────────────

  function highlightHTML(text: string): string {
    return text.replace(/<mark>/g, '<mark class="bg-[#fafafa]/15 text-[#fafafa] rounded px-0.5">').replace(/<\/mark>/g, '</mark>')
  }

  // ── Render ──────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-[#fafafa] font-sans">
      {/* Header */}
      <header className="sticky top-0 z-40 bg-[#0a0a0a]/90 backdrop-blur-md border-b border-[#1a1a1a]">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={() => setSideOpen(!sideOpen)}
              className="p-2 hover:bg-[#1a1a1a] rounded-lg transition-colors">
              <Menu size={18} />
            </button>
            <h1 className="text-lg font-semibold tracking-tight select-none">
              DocIntel
            </h1>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-[#666] hidden sm:inline">
              {stats.indexed}/{stats.total}
              <span className="text-[#444]"> indexed</span>
            </span>
            <button
              onClick={() => i18n.changeLanguage(lang === 'ru' ? 'en' : 'ru')}
              className="px-3 py-1.5 text-xs rounded-lg border border-[#2a2a2a] hover:bg-[#1a1a1a] transition-colors"
            >
              {lang === 'ru' ? 'EN' : 'RU'}
            </button>
          </div>
        </div>
      </header>

      {/* Sidebar */}
      {sideOpen && (
        <div className="fixed inset-0 z-30 flex">
          <div className="w-64 bg-[#0d0d0d] border-r border-[#1a1a1a] p-4 flex flex-col gap-6 pt-20">
            <div>
              <h2 className="text-xs text-[#666] uppercase tracking-widest mb-3">DocIntel</h2>
              <p className="text-sm leading-relaxed text-[#aaa]">
                {lang === 'ru'
                  ? 'Умный поиск по семейному архиву документов. Загружайте, находите, систематизируйте.'
                  : 'Smart search for your family document archive. Upload, find, organize.'}
              </p>
            </div>
            <div className="space-y-3">
              <p className="text-xs text-[#666] uppercase tracking-widest">
                {lang === 'ru' ? 'Статистика' : 'Statistics'}
              </p>
              {[
                [t('documents.total'), stats.total],
                [t('documents.indexed'), stats.indexed],
                [t('documents.pending'), stats.pending],
                [t('documents.errors'), stats.errors],
              ].map(([label, val]) => (
                <div key={label as string} className="flex justify-between text-sm">
                  <span className="text-[#888]">{label}</span>
                  <span className="font-medium">{val as number}</span>
                </div>
              ))}
            </div>
            <button onClick={() => setSideOpen(false)}
              className="mt-auto text-xs text-[#666] hover:text-[#aaa] transition-colors text-left">
              {lang === 'ru' ? '← Закрыть меню' : '← Close menu'}
            </button>
          </div>
          <div className="flex-1" onClick={() => setSideOpen(false)} />
        </div>
      )}

      {/* Main */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-6">
        {/* Toolbar */}
        <div className="flex flex-col sm:flex-row gap-3 mb-8">
          {/* Search */}
          <div className="flex-1 relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#555]" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={t('documents.search')}
              className="w-full pl-10 pr-4 py-2.5 bg-[#111] border border-[#2a2a2a] rounded-xl
                         text-sm text-[#fafafa] placeholder-[#555] outline-none
                         focus:border-[#444] focus:bg-[#161616] transition-all"
            />
            {hasSearchResults && search && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-[#666]">
                {searchResults!.length} found
              </span>
            )}
          </div>

          {/* View toggle */}
          <div className="flex bg-[#111] border border-[#2a2a2a] rounded-xl overflow-hidden">
            <button onClick={() => setView('grid')}
              className={`p-2.5 ${view === 'grid' ? 'bg-[#222]' : ''} transition-colors`}>
              <Grid3X3 size={16} />
            </button>
            <button onClick={() => setView('list')}
              className={`p-2.5 ${view === 'list' ? 'bg-[#222]' : ''} transition-colors`}>
              <List size={16} />
            </button>
          </div>

          {/* Upload */}
          <button onClick={() => fileRef.current?.click()}
            className="flex items-center gap-2 px-5 py-2.5 bg-[#fafafa] text-[#0a0a0a] rounded-xl
                       text-sm font-medium hover:bg-white transition-colors">
            <Upload size={16} /> {t('documents.upload_new')}
          </button>
          <input ref={fileRef} type="file" multiple hidden onChange={onFilePick}
            accept=".pdf,.jpg,.jpeg,.png,.tiff,.tif,.heic,.heif,.webp" />
        </div>

        {/* Uploading indicator */}
        {isUploading && (
          <div className="mb-4 p-3 bg-[#111] border border-[#2a2a2a] rounded-xl text-sm text-[#888]">
            {lang === 'ru' ? 'Загружаю:' : 'Uploading:'} {uploading.join(', ')}
          </div>
        )}

        {/* Drop zone */}
        <div
          onDragOver={e => { e.preventDefault(); setDropActive(true) }}
          onDragLeave={() => setDropActive(false)}
          onDrop={onDrop}
          className={`border-2 border-dashed rounded-2xl transition-all ${
            dropActive
              ? 'border-[#fafafa]/30 bg-[#111]'
              : 'border-transparent'
          }`}
        >
          {/* Empty state */}
          {!loading && docs.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <Layers size={48} className="text-[#333] mb-4" />
              <p className="text-lg text-[#666] mb-1">{t('documents.empty')}</p>
              <p className="text-sm text-[#444] max-w-xs">{t('documents.empty_hint')}</p>
            </div>
          )}

          {/* Grid view */}
          {view === 'grid' && filtered.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
              {filtered.map(doc => {
                const thumb = thumbUrl(doc)
                return (
                  <button key={doc.id} onClick={() => setSelected(doc)}
                    className="group flex flex-col bg-[#111] border border-[#1a1a1a] rounded-xl
                               overflow-hidden hover:border-[#333] hover:bg-[#161616] transition-all text-left">
                    <div className="aspect-[3/4] bg-[#0d0d0d] flex items-center justify-center
                                    overflow-hidden">
                      {thumb ? (
                        <img src={thumb} alt="" className="w-full h-full object-cover
                          group-hover:scale-105 transition-transform duration-300" />
                      ) : (
                        <FileText size={32} className="text-[#333] group-hover:text-[#555] transition-colors" />
                      )}
                    </div>
                    <div className="p-2.5">
                      <p className="text-xs font-medium truncate">{doc.original_filename}</p>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <p className="text-[10px] text-[#555] truncate">
                          {doc.doc_date?.slice(0, 10) || ''}
                          {doc.doc_type ? ` · ${doc.doc_type}` : ''}
                        </p>
                        <OcrBadge status={doc.ocr_status} />
                      </div>
                    </div>
                  </button>
                )
              })}
            </div>
          )}

          {/* List view */}
          {view === 'list' && filtered.length > 0 && (
            <div className="flex flex-col gap-px">
              {filtered.map(doc => {
                const thumb = thumbUrl(doc)
                return (
                  <button key={doc.id} onClick={() => setSelected(doc)}
                    className="flex items-center gap-4 p-3 bg-[#111] border border-[#1a1a1a]
                               rounded-xl hover:bg-[#161616] hover:border-[#333] transition-all text-left">
                    <div className="w-12 h-12 bg-[#0d0d0d] rounded-lg flex items-center justify-center
                                    shrink-0 overflow-hidden">
                      {thumb ? (
                        <img src={thumb} alt="" className="w-full h-full object-cover" />
                      ) : (
                        <FileText size={18} className="text-[#444]" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium truncate">{doc.original_filename}</p>
                        <OcrBadge status={doc.ocr_status} />
                      </div>
                      <p className="text-xs text-[#555] mt-0.5">
                        {doc.doc_date?.slice(0, 10) || '—'}
                        {doc.doc_type ? ` · ${doc.doc_type}` : ''}
                        {!doc.summary && !doc.ocr_text ? ` · ${t('documents.no_summary')}` : ''}
                      </p>
                      {doc.ocr_text && (
                        <p className="text-xs text-[#666] mt-1 line-clamp-2 whitespace-pre-line">
                          {doc.ocr_text.slice(0, 200)}
                          {doc.ocr_text.length > 200 ? '…' : ''}
                        </p>
                      )}
                    </div>
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      <span className="text-[10px] text-[#444]">{fmtSize(doc.file_size)}</span>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </main>

      {/* Document modal */}
      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm"
             onClick={e => { if (e.target === e.currentTarget) setSelected(null) }}>
          <div className="w-full max-w-3xl max-h-[90vh] bg-[#111] border border-[#2a2a2a] rounded-2xl
                          overflow-auto shadow-2xl">
            {/* Top bar */}
            <div className="flex items-center justify-between p-4 border-b border-[#1a1a1a]">
              <h2 className="text-sm font-medium truncate flex-1">{selected.original_filename}</h2>
              <div className="flex items-center gap-1">
                <a href={`/api/documents/${selected.id}/download`} download
                  className="p-2 hover:bg-[#1a1a1a] rounded-lg transition-colors"
                  title={t('documents.download')}>
                  <Download size={16} />
                </a>
                <button onClick={() => setSelected(null)}
                  className="p-2 hover:bg-[#1a1a1a] rounded-lg transition-colors">
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* Body */}
            <div className="p-5 space-y-4">
              {/* File info */}
              <div className="flex flex-wrap gap-4 text-xs text-[#666] items-center">
                <span>{fmtSize(selected.file_size)}</span>
                <span>{selected.mime_type}</span>
                {selected.doc_date && <span>{selected.doc_date.slice(0, 10)}</span>}
                {selected.doc_type && (
                  <span className="px-2 py-0.5 bg-[#1a1a1a] rounded-full text-[#aaa]">
                    {selected.doc_type}
                  </span>
                )}
                <OcrBadge status={selected.ocr_status} />
              </div>

              {/* Tags */}
              {selected.tags && selected.tags.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {selected.tags.map((tag: string) => (
                    <span key={tag}
                      className="px-2.5 py-0.5 text-xs bg-[#1a1a1a] border border-[#2a2a2a] rounded-full
                                 text-[#aaa]">
                      {tag}
                    </span>
                  ))}
                </div>
              )}

              {/* Summary */}
              {selected.summary ? (
                <div>
                  <p className="text-xs text-[#666] uppercase tracking-widest mb-1.5">
                    {lang === 'ru' ? 'Описание' : 'Summary'}
                  </p>
                  <p className="text-sm text-[#ccc] leading-relaxed">{selected.summary}</p>
                </div>
              ) : (
                <p className="text-sm text-[#555] italic">{t('documents.no_summary')}</p>
              )}

              {/* OCR Text */}
              {selected.ocr_text && (
                <div>
                  <p className="text-xs text-[#666] uppercase tracking-widest mb-1.5">
                    {lang === 'ru' ? 'Распознанный текст' : 'Recognized Text'}
                  </p>
                  <p className="text-xs text-[#888] leading-relaxed whitespace-pre-line bg-[#0d0d0d]
                    border border-[#1a1a1a] rounded-xl p-3 max-h-40 overflow-y-auto">
                    {selected.ocr_text}
                  </p>
                </div>
              )}

              {/* Preview thumbnail */}
              {selected.thumbnail_path && (
                <div className="rounded-xl overflow-hidden bg-[#0d0d0d]">
                  <img
                    src={`/api/documents/${selected.id}/thumbnail`}
                    alt=""
                    className="w-full max-h-[500px] object-contain"
                  />
                </div>
              )}
              {!selected.thumbnail_path && (
                <div className="aspect-[3/4] max-h-[400px] bg-[#0d0d0d] rounded-xl
                                flex items-center justify-center text-[#333]">
                  <FileText size={64} />
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="border-t border-[#1a1a1a] mt-12 py-6 text-center text-xs text-[#333]">
        DocIntel &middot; {lang === 'ru' ? 'Семейный архив документов' : 'Family Document Archive'}
      </footer>
    </div>
  )
}
