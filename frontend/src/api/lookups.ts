// Small cached lookups for display names/codes. The API returns reference ids
// on delivery/advance rows (only payouts embed a farmer name), so lists resolve
// names from these maps. Caches are cleared after a create so new rows appear.

import type { CropGrade, Farmer } from "./types";
import { collectPages } from "./client";

let farmerMap: Map<number, Farmer> | null = null;
let gradeMap: Map<number, CropGrade> | null = null;

/**
 * Load **every** farmer, not just the first page. The reference collections are
 * paginated (default 20, max 100), so selection UIs must walk the `next` links or
 * they silently hide records beyond the first page.
 */
export async function loadFarmerMap(signal?: AbortSignal): Promise<Map<number, Farmer>> {
  if (!farmerMap) {
    const farmers = await collectPages<Farmer>("/farmers/", {
      query: { page_size: 100, ordering: "id" },
      signal,
    });
    farmerMap = new Map(farmers.map((farmer) => [farmer.id, farmer]));
  }
  return farmerMap;
}

/** Load **every** grade across all pages (same reasoning as farmers). */
export async function loadGradeMap(signal?: AbortSignal): Promise<Map<number, CropGrade>> {
  if (!gradeMap) {
    const grades = await collectPages<CropGrade>("/grades/", {
      query: { page_size: 100, ordering: "id" },
      signal,
    });
    gradeMap = new Map(grades.map((grade) => [grade.id, grade]));
  }
  return gradeMap;
}

export function invalidateFarmerMap(): void {
  farmerMap = null;
}

export function invalidateGradeMap(): void {
  gradeMap = null;
}

export function farmerLabel(farmers: Map<number, Farmer> | undefined, id: number | null): string {
  if (id === null) return "—";
  return farmers?.get(id)?.name ?? `#${id}`;
}

export function gradeLabel(grades: Map<number, CropGrade> | undefined, id: number | null): string {
  if (id === null) return "—";
  const grade = grades?.get(id);
  return grade ? `${grade.crop_name} · ${grade.code}` : `#${id}`;
}
