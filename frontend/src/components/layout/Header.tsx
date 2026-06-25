import { useEffect, useState } from "react";
import { Settings, Globe, Moon, Sun } from "lucide-react";
import { useT, type Lang } from "../../i18n";

const LANG_CYCLE: Lang[] = ["en", "ru", "fr"];
const LANG_NEXT_LABEL: Record<Lang, string> = { en: "RU", ru: "FR", fr: "EN" };
const LANG_NEXT_TITLE: Record<Lang, string> = { en: "Русский", ru: "Français", fr: "English" };
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
            onClick={() => setLang(LANG_CYCLE[(LANG_CYCLE.indexOf(lang) + 1) % LANG_CYCLE.length])}
            aria-label="Switch language"
            title={LANG_NEXT_TITLE[lang]}
          >
            <Globe size={15} />
            <span>{LANG_NEXT_LABEL[lang]}</span>
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
