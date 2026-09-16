export function safeDestination(value: unknown): string {
  if (typeof value !== "string" || !(value === "/app" || value.startsWith("/app/")) || value.startsWith("//")) return "/app";
  try {
    const url = new URL(value, window.location.origin);
    return url.origin === window.location.origin ? `${url.pathname}${url.search}${url.hash}` : "/app";
  } catch {
    return "/app";
  }
}

export function rememberDestination(value: unknown): string {
  const destination = safeDestination(value);
  sessionStorage.setItem("sf:next", destination);
  return destination;
}
