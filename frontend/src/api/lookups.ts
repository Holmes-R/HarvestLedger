// Small cached lookups for display names/codes. The API returns reference ids
// on delivery/advance rows (only payouts embed a farmer name), so lists resolve
// names from these maps. Caches are cleared after a create so new rows appear.

import type { CropGrade, Farmer } from "./types";
import { listFarmers, listGrades } from "./endpoints";

let farmerMap: Map<number, Farmer> | null = null;
let gradeMap: Map<number, CropGrade> | null = null;

export async function loadFarmerMap(signal?: AbortSignal): Promise<Map<number, Farmer>> {
  if (!farmerMap) {
    const page = await listFarmers({ page_size: 100, ordering: "id" }, { signal });
    farmerMap = new Map(page.results.map((farmer) => [farmer.id, farmer]));
  }
  return farmerMap;
}

export async function loadGradeMap(signal?: AbortSignal): Promise<Map<number, CropGrade>> {
  if (!gradeMap) {
    const page = await listGrades({ page_size: 100, ordering: "id" }, { signal });
    gradeMap = new Map(page.results.map((grade) => [grade.id, grade]));
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
