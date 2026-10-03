function stripHtml(value) {
  return String(value || "")
    .replace(/<[^>]*>/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function errorMessage(error, fallback = "Something went wrong.") {
  const messages = Array.isArray(error?.messages) ? error.messages : [];
  const message = messages
    .map((item) => (typeof item === "string" ? item : item?.message))
    .map(stripHtml)
    .filter(Boolean)[0];
  return message || stripHtml(error?.response?.data?.message) || fallback;
}

export const getFrappeErrorMessage = errorMessage;
