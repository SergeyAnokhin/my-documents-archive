import { createContext, useContext } from "react";
import { en } from "./en";
import { ru } from "./ru";
import type { Translations } from "./en";

export type Lang = "en" | "ru";

export const translations: Record<Lang, Translations> = { en, ru };

export const LangContext = createContext<{
  lang: Lang;
  t: Translations;
  setLang: (l: Lang) => void;
}>({ lang: "en", t: en, setLang: () => {} });

export function useT() {
  return useContext(LangContext);
}

export { en, ru };
export type { Translations };
