import { Modal } from "./Modal";
import { useT } from "../../i18n";

interface Props {
  open: boolean;
  onClose: () => void;
}

const shortcuts = [
  { key: "/",       action_en: "Focus search",         action_ru: "Перейти в поиск" },
  { key: "Esc",     action_en: "Close / clear search", action_ru: "Закрыть / сбросить" },
  { key: "← →",    action_en: "Prev / next document",  action_ru: "Предыдущий / следующий" },
  { key: "1",       action_en: "List view",             action_ru: "Режим списка" },
  { key: "2",       action_en: "Grid view",             action_ru: "Режим сетки" },
  { key: "+ −",    action_en: "Larger / smaller grid", action_ru: "Размер сетки" },
  { key: "?",       action_en: "Show shortcuts",        action_ru: "Показать сокращения" },
];

export function KeyboardHelp({ open, onClose }: Props) {
  const { lang } = useT();
  return (
    <Modal open={open} onClose={onClose} title={lang === "ru" ? "Горячие клавиши" : "Keyboard shortcuts"} size="sm">
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <tbody>
          {shortcuts.map((s) => (
            <tr key={s.key} style={{ borderBottom: "1px solid var(--color-border-soft)" }}>
              <td style={{ padding: "8px 0", width: 80 }}>
                <kbd style={{
                  display: "inline-block",
                  padding: "2px 8px",
                  background: "var(--color-tag)",
                  borderRadius: "var(--radius-sm)",
                  fontFamily: "var(--font-mono)",
                  fontSize: ".8125rem",
                  fontWeight: 600,
                  letterSpacing: ".02em",
                  border: "1.5px solid var(--color-border)",
                }}>{s.key}</kbd>
              </td>
              <td style={{ padding: "8px 0 8px 12px", fontSize: ".9rem", color: "var(--color-ink-muted)" }}>
                {lang === "ru" ? s.action_ru : s.action_en}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Modal>
  );
}
