"use client";

import type { ReactNode } from "react";
import { useAppSelector } from "@/lib/hooks";
import type { Role } from "./data";

export default function RoleOnly({
  roles,
  children,
}: {
  roles: Role[];
  children: ReactNode;
}) {
  const role = useAppSelector((state) => state.role.value);
  if (!roles.includes(role)) return null;
  return <>{children}</>;
}
