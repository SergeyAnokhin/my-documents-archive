export const en = {
  appName: "DocIntel",
  appTagline: "Your personal document archive",

  // Nav
  myDocuments: "My Documents",
  adminPanel: "Administration",

  // Home
  searchPlaceholder: "Search documents…",
  searchMode: {
    fulltext: "Text",
    semantic: "Smart",
    hybrid: "Best",
  },
  uploadTitle: "Add Documents",
  uploadHint: "Drag files here or click to select",
  uploadButton: "Choose Files",
  uploadAccept: "PDF, JPEG, PNG, TIFF, HEIC, WEBP",
  syncButton: "Sync Library",
  syncSuccess: "Sync complete — {{new}} new document(s) found",
  viewList: "List",
  viewGrid: "Grid",

  // Document card
  noSummary: "Document not yet analyzed",
  noDate: "Date unknown",
  docType: {
    invoice: "Invoice",
    contract: "Contract",
    certificate: "Certificate",
    letter: "Letter",
    medical: "Medical",
    tax: "Tax",
    id: "Identity",
    receipt: "Receipt",
    other: "Document",
  },
  status: {
    pending: "Pending",
    done: "Indexed",
    error: "Error",
    skipped: "Skipped",
  },
  download: "Download",
  editTags: "Edit Tags",

  // Document viewer
  page: "Page",
  of: "of",
  recognizedText: "Recognized Text",
  metadata: "Details",
  close: "Close",

  // Empty states
  noDocuments: "No documents yet",
  noDocumentsHint: "Upload a file or sync your library to get started",
  noResults: "No documents found",
  noResultsHint: "Try a different search query",

  // Admin
  admin: {
    title: "Administration",
    tabs: {
      sources: "Sources",
      indexing: "Indexing",
      ai: "AI Settings",
      log: "Log",
    },
    sources: {
      title: "Watched Folders",
      addFolder: "Add Folder",
      folderPath: "Folder path",
      noFolders: "No folders configured",
    },
    indexing: {
      title: "Indexing",
      total: "Total",
      indexed: "OCR Done",
      analyzed: "Analyzed",
      embedded: "Embedded",
      pending: "Pending",
      errors: "Errors",
      cost: "API Cost",
      batchButton: "Start Batch Indexing",
      reclassifyButton: "Re-classify All",
      syncButton: "Sync Library",
    },
    ai: {
      title: "AI Providers",
      addProvider: "Add Provider",
      noProviders: "No AI providers configured",
      noProvidersHint: "Add a provider below to enable automatic AI analysis after OCR",
      providerName: "Name",
      providerType: "Provider",
      apiKey: "API Key",
      modelName: "Model (optional, uses default if empty)",
      enableVision: "Enable AI Vision",
      visionHint: "Sends document image to vision model before analysis. Improves accuracy on complex layouts.",
    },
    log: {
      title: "Event Log",
      empty: "No events yet",
      step: "Step",
      status: "Status",
      message: "Message",
      cost: "Cost",
      time: "Time",
    },
  },

  // Filters
  filters: {
    title: "Filters",
    year: "Year",
    month: "Month",
    type: "Document type",
    language: "Language",
    status: "Status",
    clear: "Clear filters",
    allYears: "All years",
    allMonths: "All months",
    allTypes: "All types",
    allLanguages: "All languages",
    allStatuses: "All statuses",
  },

  // Misc
  loading: "Loading…",
  error: "Something went wrong",
  save: "Save",
  cancel: "Cancel",
  delete: "Delete",
  confirm: "Confirm",
  add: "Add",
  enabled: "Enabled",
  disabled: "Disabled",
  uploading: "Uploading…",
  uploaded: "Uploaded!",
};

export type Translations = typeof en;
