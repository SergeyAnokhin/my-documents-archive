import { createContext, useContext, useState, type ReactNode } from "react";

interface AdvancedModeContextType {
  advancedMode: boolean;
  setAdvancedMode: (v: boolean) => void;
}

const AdvancedModeContext = createContext<AdvancedModeContextType>({
  advancedMode: false,
  setAdvancedMode: () => {},
});

function getInitial(): boolean {
  try {
    return localStorage.getItem("advanced-mode") === "true";
  } catch {
    return false;
  }
}

export function AdvancedModeProvider({ children }: { children: ReactNode }) {
  const [advancedMode, setAdvancedModeState] = useState(getInitial);

  const setAdvancedMode = (v: boolean) => {
    setAdvancedModeState(v);
    try { localStorage.setItem("advanced-mode", String(v)); } catch {}
  };

  return (
    <AdvancedModeContext.Provider value={{ advancedMode, setAdvancedMode }}>
      {children}
    </AdvancedModeContext.Provider>
  );
}

export const useAdvancedMode = () => useContext(AdvancedModeContext);
