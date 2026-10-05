"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import Rail from "./Rail";
import Panel from "./Panel";
import Topbar from "./Topbar";
import Toast from "./Toast";
import { groupForPath, titleForPath, visibleNavItems } from "./data";
import { useAppSelector } from "@/lib/hooks";

function derivedGroup(pathname: string): string {
  return pathname === "/" ? "home" : groupForPath(pathname);
}

/** Routes reachable with no token — each manages its own full-page layout,
 * no Rail/Panel/Topbar chrome, and must be exempt from the auth-redirect
 * below (otherwise visiting them with no token just bounces straight back
 * to /login before rendering anything). */
const PUBLIC_ROUTES = ["/login", "/setup"];

export default function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const role = useAppSelector((state) => state.role.value);
  const appId = useAppSelector((state) => state.app.value);
  const token = useAppSelector((state) => state.auth.token);
  const permissions = useAppSelector((state) => state.auth.employee?.permissions);

  // No SSR/cookie auth in this app — auth state only exists once the client
  // has hydrated from localStorage (see lib/store.ts), so the redirect check
  // below waits for a real mount before acting on a possibly-stale "logged
  // out" reading during the server-rendered first pass.
  const [mounted, setMounted] = useState(false);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (mounted && !token && !PUBLIC_ROUTES.includes(pathname)) router.replace("/login");
  }, [mounted, token, pathname, router]);

  const [routedPathname, setRoutedPathname] = useState(pathname);
  const [activeGroup, setActiveGroup] = useState(() => derivedGroup(pathname));
  const [panelCollapsed, setPanelCollapsed] = useState(() => pathname === "/");

  // A rail click can navigate to an href that's ambiguous between groups (e.g.
  // "/" is both the Home landing page and the Workspace group's Dashboard
  // item). This remembers which group the user actually asked for so the
  // sync below doesn't re-derive the wrong one once the route catches up.
  const [pendingRailGroup, setPendingRailGroup] = useState<{ path: string; group: string } | null>(null);

  // Re-derive the rail/panel state when navigation changes the route, without
  // an effect (which would cause an extra render); the reveal-panel-without-
  // navigating case below still overrides this via direct setState in the handler.
  if (pathname !== routedPathname) {
    setRoutedPathname(pathname);
    if (pendingRailGroup && pendingRailGroup.path === pathname) {
      setPendingRailGroup(null);
      setActiveGroup(pendingRailGroup.group);
      setPanelCollapsed(false);
    } else {
      const g = derivedGroup(pathname);
      setActiveGroup(g);
      setPanelCollapsed(g === "home");
    }
  }

  function handleRailClick(group: string) {
    if (group === "home") {
      setPendingRailGroup(null);
      router.push("/");
      setActiveGroup("home");
      setPanelCollapsed(true);
      return;
    }
    const currentPathGroup = pathname === "/" ? "home" : groupForPath(pathname);
    if (currentPathGroup !== group) {
      const items = visibleNavItems(group, role, appId, permissions);
      if (items.length && items[0].href !== pathname) {
        setPendingRailGroup({ path: items[0].href, group });
        router.push(items[0].href);
        setActiveGroup(group);
        setPanelCollapsed(false);
        return;
      }
    }
    setPendingRailGroup(null);
    setActiveGroup(group);
    setPanelCollapsed(false);
  }

  function handleBrandClick() {
    // "home" has no panel of its own (it's the rail's dedicated icon), so
    // reveal the workspace group's panel instead of opening an empty one.
    if (activeGroup === "home") {
      setActiveGroup("workspace");
    }
    setPanelCollapsed(false);
  }

  if (PUBLIC_ROUTES.includes(pathname)) return <>{children}</>;

  // Not yet known whether we're authenticated (pre-mount) or definitely not
  // (redirect effect above is about to fire) — render nothing rather than a
  // flash of the app chrome around content the user isn't authorized to see.
  if (!mounted || !token) return null;

  return (
    <div className={`app${panelCollapsed ? " panel-collapsed" : ""}`}>
      <Rail
        activeGroup={activeGroup}
        onGroupClick={handleRailClick}
        onBrandClick={handleBrandClick}
        showBrand={panelCollapsed}
      />
      <Panel
        activeGroup={activeGroup}
        pathname={pathname}
        onCollapse={() => setPanelCollapsed((c) => !c)}
      />
      <div className="main">
        <Topbar />
        <div className="crumbbar">
          <b>{titleForPath(pathname)}</b>
        </div>
        <div className="content">{children}</div>
      </div>
      <Toast />
    </div>
  );
}
