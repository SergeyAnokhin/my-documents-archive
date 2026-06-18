import { useState } from "react";
import { Header } from "./components/layout/Header";
import { AdminPanel } from "./components/admin/AdminPanel";
import { HomePage } from "./pages/HomePage";
import { LangContext, translations, type Lang } from "./i18n";

export default function App() {
  const [lang, setLang] = useState<Lang>("ru");
  const [adminOpen, setAdminOpen] = useState(false);

  return (
    <LangContext.Provider value={{ lang, t: translations[lang], setLang }}>
      <Header onAdminOpen={() => setAdminOpen(true)} />
      <HomePage />
      <AdminPanel open={adminOpen} onClose={() => setAdminOpen(false)} />
    </LangContext.Provider>
  );
}
