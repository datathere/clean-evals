import { useEffect } from "react";
import { create } from "zustand";

type Theme = "light" | "dark";

interface ThemeStore {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggle: () => void;
}

const initial: Theme = (() => {
  if (typeof localStorage === "undefined") return "light";
  const saved = localStorage.getItem("clean-evals-theme") as Theme | null;
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
})();

export const useThemeStore = create<ThemeStore>((set, get) => ({
  theme: initial,
  setTheme: (t) => {
    localStorage.setItem("clean-evals-theme", t);
    document.documentElement.classList.toggle("dark", t === "dark");
    set({ theme: t });
  },
  toggle: () => get().setTheme(get().theme === "light" ? "dark" : "light"),
}));

export function useTheme() {
  const { theme } = useThemeStore();
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);
}
