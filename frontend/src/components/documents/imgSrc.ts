export function resolveImgSrc(
  previewB64: string | null | undefined,
  rawSrc: string | null,
): string | undefined {
  if (previewB64) return `data:image/jpeg;base64,${previewB64}`;
  return rawSrc ?? undefined;
}
