import { type HTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className={cn("w-full text-sm", className)}>{children}</table>
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  return (
    <thead className="bg-muted/40 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
      {children}
    </thead>
  );
}

export function TR(props: HTMLAttributes<HTMLTableRowElement>) {
  return <tr {...props} className={cn("border-b last:border-0", props.className)} />;
}

export function TH({ children, className }: { children?: ReactNode; className?: string }) {
  return <th className={cn("px-3 py-2 font-medium", className)}>{children}</th>;
}

export function TD({ children, className }: { children: ReactNode; className?: string }) {
  return <td className={cn("px-3 py-2 align-middle", className)}>{children}</td>;
}
