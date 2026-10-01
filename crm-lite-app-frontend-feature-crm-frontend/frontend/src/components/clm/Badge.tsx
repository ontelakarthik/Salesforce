import type { CSSProperties, ReactNode } from "react";

export type BadgeVariant = "green" | "amber" | "red" | "blue" | "teal" | "violet" | "gray";

export default function Badge({
  variant = "gray",
  dot = false,
  children,
  style,
}: {
  variant?: BadgeVariant;
  dot?: boolean;
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <span className={`badge b-${variant}`} style={style}>
      {dot && <span className="dot" />}
      {children}
    </span>
  );
}
