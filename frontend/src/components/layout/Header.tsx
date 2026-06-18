import { Settings, Globe } from "lucide-react";
import { useT, type Lang } from "../../i18n";
import { IndexingBadge } from "../ui/IndexingBadge";
import "./Header.css";

interface Props {
  onAdminOpen: () => void;
}

export function Header({ onAdminOpen }: Props) {
  const { t, lang, setLang } = useT();

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
