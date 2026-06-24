import { useEffect, useState } from "react";
import { Settings, Globe, Moon, Sun } from "lucide-react";
import { useT, type Lang } from "../../i18n";
import { IndexingBadge } from "../ui/IndexingBadge";
import "./Header.css";

function getInitialTheme(): "light" | "dark" {
  try {
    const stored = localStorage.getItem("theme");
    if (stored === "dark" || stored === "light") return stored;
    if (window.matchMedia("(prefers-color-scheme: dark)").matches) return "dark";
  } catch {}
  return "light";
}

function applyTheme(theme: "light" | "dark") {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("theme", theme); } catch {}
}

interface Props {
  onAdminOpen: () => void;
}

export function Header({ onAdminOpen }: Props) {
  const { t, lang, setLang } = useT();
  const [theme, setTheme] = useState<"light" | "dark">(getInitialTheme);

  useEffect(() => { applyTheme(theme); }, [theme]);

  const toggleTheme = () => setTheme(t => t === "light" ? "dark" : "light");

  return (
    <header className="header">
      <div className="container header-inner">
        {/* Logo */}
        <div className="header-logo">
          <span className="header-logo-mark">D</span>
          <span className="header-logo-name">{t.appName}</span>
        </div>

        {/* Actions */}
        <div className="header-actions">
          <IndexingBadge />

          {/* Theme toggle */}
          <button
            className="icon-btn"
            onClick={toggleTheme}
            aria-label={theme === "dark" ? "Light mode" : "Dark mode"}
            title={theme === "dark" ? "Light mode" : "Dark mode"}
          >
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </button>

          {/* Language switcher */}
          <button
            className="lang-btn"
            onClick={() => setLang(lang === "en" ? "ru" : "en")}
            aria-label="Switch language"
            title={lang === "en" ? "Русский" : "English"}
          >
            <Globe size={15} />
            <span>{lang === "en" ? "RU" : "EN"}</span>
          </button>

          {/* Admin */}
          <button
            className="icon-btn"
            onClick={onAdminOpen}
            aria-label={t.adminPanel}
            title={t.adminPanel}
          >
            <Settings size={18} />
          </button>
        </div>
      </div>
    </header>
  );
}
