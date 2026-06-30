import { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Header } from "./components/layout/Header";
import { AdminPanel } from "./components/admin/AdminPanel";
import { TasksPanel, type TaskPreCreate } from "./components/tasks/TasksPanel";
import { HomePage } from "./pages/HomePage";
import { LabPage } from "./pages/LabPage";
import { LangContext, translations, type Lang } from "./i18n";
import { AdvancedModeProvider } from "./contexts/AdvancedModeContext";
import { getCustomTypeIcons, getCustomTypeNames } from "./api/documents";
import { setCustomTypeIcons, setCustomTypeNames } from "./components/documents/typeIcons";

function HomeRoute() {
  const [adminOpen, setAdminOpen] = useState(false);
  const [tasksOpen, setTasksOpen] = useState(false);
  const [tasksPreCreate, setTasksPreCreate] = useState<TaskPreCreate | null>(null);

  // Listen for requests from HomePage to open tasks panel with a pre-configured task
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<TaskPreCreate>).detail;
      setTasksPreCreate(detail);
      setTasksOpen(true);
    };
    window.addEventListener("docintell:open-tasks-create", handler);
    return () => window.removeEventListener("docintell:open-tasks-create", handler);
  }, []);

  return (
    <>
      <Header onAdminOpen={() => setAdminOpen(true)} onTasksOpen={() => setTasksOpen(true)} />
      <HomePage />
      <AdminPanel open={adminOpen} onClose={() => setAdminOpen(false)} />
      <TasksPanel
        open={tasksOpen}
        onClose={() => setTasksOpen(false)}
        preCreate={tasksPreCreate}
        onPreCreateConsumed={() => setTasksPreCreate(null)}
      />
    </>
  );
}

const LANG_KEY = "lang";

function getInitialLang(): Lang {
  try {
    const stored = localStorage.getItem(LANG_KEY);
    if (stored === "en" || stored === "ru" || stored === "fr") return stored;
  } catch {}
  return "en"; // English is the default on a fresh install
}

export default function App() {
  const [lang, setLangState] = useState<Lang>(getInitialLang);

  const setLang = (l: Lang) => {
    setLangState(l);
    try { localStorage.setItem(LANG_KEY, l); } catch {}
  };

  useEffect(() => {
    getCustomTypeIcons().then(setCustomTypeIcons).catch(() => {});
    getCustomTypeNames().then(setCustomTypeNames).catch(() => {});
  }, []);

  return (
    <LangContext.Provider value={{ lang, t: translations[lang], setLang }}>
      <AdvancedModeProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<HomeRoute />} />
            <Route path="/lab/:id" element={<LabPage />} />
          </Routes>
        </BrowserRouter>
      </AdvancedModeProvider>
    </LangContext.Provider>
  );
}
