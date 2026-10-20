import { useEffect, useState } from "react";

// A tiny hash router: no dependency, deep-linkable URLs like `#/payouts/12`.
// Section names are the first path segment, the second is an optional id and an
// optional query string carries context (for example `#/deliveries/12?from=ledger&farmer=3`).

export interface Route {
  section: string;
  id: string | null;
  params: URLSearchParams;
}

const DEFAULT_SECTION = "deliveries";

function parse(hash: string): Route {
  const clean = hash.replace(/^#\/?/, "");
  const [path, search = ""] = clean.split("?");
  const [section, id] = path.split("/");
  return {
    section: section || DEFAULT_SECTION,
    id: id || null,
    params: new URLSearchParams(search),
  };
}

function hashTarget(to: string): string {
  return to.startsWith("#") ? to : `#${to.startsWith("/") ? "" : "/"}${to}`;
}

export function navigate(to: string): void {
  const target = hashTarget(to);
  if (window.location.hash === target) return;
  window.location.hash = target;
}

/**
 * Update the URL without adding a history entry, then notify the router. Used
 * when a screen's selection is part of the linkable context but should not make
 * every click a Back-button step.
 */
export function replaceHash(to: string): void {
  const target = hashTarget(to);
  if (window.location.hash === target) return;
  window.history.replaceState(null, "", target);
  window.dispatchEvent(new Event("hashchange"));
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
