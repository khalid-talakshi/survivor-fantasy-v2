const callbackErrorKeys = ["error", "error_code", "error_description"];
export const unauthorizedReasonStorageKey = "sf:auth-reason";

export function rememberUnauthorizedReason() {
  sessionStorage.setItem(unauthorizedReasonStorageKey, "unauthorized");
}

export function consumeUnauthorizedReason() {
  const reason = sessionStorage.getItem(unauthorizedReasonStorageKey);
  sessionStorage.removeItem(unauthorizedReasonStorageKey);
  return reason === "unauthorized";
}

export function hasAuthCallbackError(search: string, hash: string) {
  return [search, hash].some((part) => {
    const params = new URLSearchParams(part.startsWith("?") || part.startsWith("#") ? part.slice(1) : part);
    return callbackErrorKeys.some((key) => params.has(key));
  });
}
