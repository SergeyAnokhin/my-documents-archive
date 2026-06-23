import { useState } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Header } from "./components/layout/Header";
import { AdminPanel } from "./components/admin/AdminPanel";
import { HomePage } from "./pages/HomePage";
import { LabPage } from "./pages/LabPage";
import { LangContext, translations, type Lang } from "./i18n";

function HomeRoute() {
  const [adminOpen, setAdminOpen] = useState(false);
  return (
    <>
      <Header onAdminOpen={() => setAdminOpen(true)} />
      <HomePage />
      <AdminPanel open={adminOpen} onClose={() => setAdminOpen(false)} />
    </>
  );
}

export default function App() {
  const [lang, setLang] = useState<Lang>("ru");

  return (
    <LangContext.Provider value={{ lang, t: translations[lang], setLang }}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<HomeRoute />} />
          <Route path="/lab/:id" element={<LabPage />} />
        </Routes>
      </BrowserRouter>
    </LangContext.Provider>
  );
}
