export const CURRENT_CONTENT_REVISION = 1 as const;

export type SavedSceneLocation = {
  sceneId?: unknown;
  sceneIndex?: unknown;
};

/**
 * Resolve a saved position against the current authored sequence.
 *
 * Stable scene ids survive insertions and removals before the saved scene. The
 * numeric index remains a compatibility fallback for older saves and is always
 * clamped to a valid position in the current sequence.
 */
export function resolveSavedSceneIndex(
  savedLocation: SavedSceneLocation | null | undefined,
  sceneIds: readonly string[],
): number {
  if (sceneIds.length === 0) return 0;

  const savedSceneId = savedLocation?.sceneId;
  if (typeof savedSceneId === "string" && savedSceneId.length > 0) {
    const stableIndex = sceneIds.indexOf(savedSceneId);
    if (stableIndex >= 0) return stableIndex;
  }

  const savedIndex = savedLocation?.sceneIndex;
  const fallbackIndex =
    typeof savedIndex === "number" && Number.isFinite(savedIndex)
      ? Math.trunc(savedIndex)
      : 0;

  return Math.min(sceneIds.length - 1, Math.max(0, fallbackIndex));
}

/**
 * Preserve a run's memory baseline without allowing corrupt or future values
 * to exceed the profile's current memory. Missing legacy values start at the
 * current total so loading an old save cannot manufacture retroactive gains.
 */
export function normalizeRunStartMemory(value: unknown, currentMemory: unknown): number {
  const safeCurrentMemory =
    typeof currentMemory === "number" && Number.isFinite(currentMemory)
      ? Math.max(0, currentMemory)
      : 0;

  if (typeof value !== "number" || !Number.isFinite(value)) {
    return safeCurrentMemory;
  }

  return Math.min(safeCurrentMemory, Math.max(0, value));
}
