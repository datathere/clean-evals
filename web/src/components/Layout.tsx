import { type ReactNode } from "react";
import {
  Boxes,
  CalendarClock,
  Database,
  FileBarChart,
  Moon,
  Sun,
} from "lucide-react";
import { Logo } from "@/components/Logo";
import { cn } from "@/lib/utils";
import { useThemeStore } from "@/lib/theme";

interface NavItem {
  key: string;
  label: string;
  href: string;
  icon: typeof Database;
}

const NAV: NavItem[] = [
  { key: "datasets", label: "Datasets", href: "/datasets", icon: Database },
  { key: "runs", label: "Runs", href: "/runs", icon: FileBarChart },
  { key: "models", label: "Models", href: "/models", icon: Boxes },
  { key: "schedules", label: "Schedules", href: "/schedules", icon: CalendarClock },
];

interface Props {
  children: ReactNode;
  currentRoute: string;
  navigate: (path: string) => void;
}

export function Layout({ children, currentRoute, navigate }: Props) {
  const { theme, toggle } = useThemeStore();
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b sticky top-0 bg-background/80 backdrop-blur z-30">
        <div className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
          <a
            href="/datasets"
            onClick={(e) => {
              e.preventDefault();
              navigate("/datasets");
            }}
            className="flex items-center gap-2 font-semibold tracking-tight"
          >
            <Logo className="size-7" />
            <span>clean-evals</span>
          </a>
          <nav className="flex items-center gap-1 text-sm">
            {NAV.map((item) => {
              // The builder edits datasets, so it highlights the Datasets item.
              const active =
                currentRoute === item.key ||
                (item.key === "datasets" && currentRoute === "builder");
              const Icon = item.icon;
              return (
                <a
                  key={item.key}
                  href={item.href}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate(item.href);
                  }}
                  className={cn(
                    "px-3 py-1.5 rounded-md inline-flex items-center gap-1.5 transition-colors",
                    active
                      ? "bg-secondary text-secondary-foreground"
                      : "text-muted-foreground hover:text-foreground hover:bg-secondary/60",
                  )}
                >
                  <Icon className="size-4" />
                  {item.label}
                </a>
              );
            })}
          </nav>
          <button
            type="button"
            aria-label="Toggle theme"
            onClick={toggle}
            className="size-8 grid place-items-center rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/60"
          >
            {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </button>
        </div>
      </header>
      <main className="flex-1 max-w-7xl mx-auto w-full px-6 py-8">{children}</main>
      <footer className="border-t py-4 text-center text-xs text-muted-foreground">
        clean-evals · by datathere ·{" "}
        <a
          href="https://github.com/datathere/clean-evals"
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-foreground"
        >
          github.com/datathere/clean-evals
        </a>
      </footer>
    </div>
  );
}
