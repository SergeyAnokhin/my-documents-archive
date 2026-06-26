import { useState } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Header } from "./components/layout/Header";
import { AdminPanel } from "./components/admin/AdminPanel";
import { TasksPanel } from "./components/tasks/TasksPanel";
import { HomePage } from "./pages/HomePage";
import { LabPage } from "./pages/LabPage";
import { LangContext, translations, type Lang } from "./i18n";
import { AdvancedModeProvider } from "./contexts/AdvancedModeContext";

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

export default function App() {
  const [lang, setLang] = useState<Lang>("ru");

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
