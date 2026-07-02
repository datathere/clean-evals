import { cva, type VariantProps } from "class-variance-authority";
import { type HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium border",
  {
    variants: {
      variant: {
        default: "bg-secondary text-secondary-foreground border-transparent",
        success: "bg-success/10 text-success border-success/30",
        warning: "bg-warning/10 text-warning border-warning/30",
        destructive: "bg-destructive/10 text-destructive border-destructive/30",
        outline: "border-border text-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

interface Props extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...rest }: Props) {
  return <span className={cn(badgeVariants({ variant, className }))} {...rest} />;
}
