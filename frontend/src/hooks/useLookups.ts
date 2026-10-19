import { loadFarmerMap, loadGradeMap } from "../api/lookups";
import { useAsync } from "./useAsync";

/** Cached farmer/grade maps for turning ids in lists and details into labels. */
export function useLookups() {
  return useAsync(async (signal) => {
    const [farmers, grades] = await Promise.all([
      loadFarmerMap(signal),
      loadGradeMap(signal),
    ]);
    return { farmers, grades };
  }, []);
}
