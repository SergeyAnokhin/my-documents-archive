import { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Header } from "./components/layout/Header";
import { AdminPanel } from "./components/admin/AdminPanel";
import { TasksPanel } from "./components/tasks/TasksPanel";
import { HomePage } from "./pages/HomePage";
import { LabPage } from "./pages/LabPage";
import { LangContext, translations, type Lang } from "./i18n";
import { AdvancedModeProvider } from "./contexts/AdvancedModeContext";
import { getCustomTypeIcons } from "./api/documents";
import { setCustomTypeIcons } from "./components/documents/typeIcons";

function HomeRoute() {
  const [adminOpen, setAdminOpen] = useState(false);
  const [tasksOpen, setTasksOpen] = useState(false);
  return (
    <>
      <Header onAdminOpen={() => setAdminOpen(true)} onTasksOpen={() => setTasksOpen(true)} />
      <HomePage />
      <AdminPanel open={adminOpen} onClose={() => setAdminOpen(false)} />
      <TasksPanel open={tasksOpen} onClose={() => setTasksOpen(false)} />
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
