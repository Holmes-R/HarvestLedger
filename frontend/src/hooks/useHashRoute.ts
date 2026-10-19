import { useEffect, useState } from "react";

// A tiny hash router: no dependency, deep-linkable URLs like `#/payouts/12`.
// Section names are the first path segment; the second is an optional id.

export interface Route {
  section: string;
  id: string | null;
}

const DEFAULT_SECTION = "deliveries";

function parse(hash: string): Route {
  const clean = hash.replace(/^#\/?/, "");
  const [section, id] = clean.split("/");
  return { section: section || DEFAULT_SECTION, id: id || null };
}

export function navigate(to: string): void {
  const target = to.startsWith("#") ? to : `#${to.startsWith("/") ? "" : "/"}${to}`;
  if (window.location.hash === target) return;
  window.location.hash = target;
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));

  useEffect(() => {
    const onHashChange = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return route;
}
