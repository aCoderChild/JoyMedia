// Word-level diff for an AI prompt revision: the words the planner added appear
// as segments the UI can highlight, so a person sees what changed before it is
// applied rather than having the prompt silently overwritten.

function clean(word) {
  // Keep @mentions whole; strip surrounding punctuation for the comparison only.
  return word.toLowerCase().replace(/[^\w@]/g, "");
}

/**
 * @returns {{text:string, added:boolean}[]} segments in order, ready to render.
 */
export function diffPromptAdditions(original = "", revised = "") {
  const origText = String(original || "").trim();
  const newText = String(revised || "").trim();
  if (!newText) return [];
  if (!origText) return [{ text: newText, added: true }];

  // Common case: the revision keeps the original and appends to it.
  if (newText.toLowerCase().startsWith(origText.toLowerCase())) {
    const kept = newText.slice(0, origText.length);
    const appended = newText.slice(origText.length);
    const segments = [{ text: kept, added: false }];
    if (appended.trim()) segments.push({ text: appended, added: true });
    return segments;
  }

  // Otherwise, mark words not present in the original as additions.
  const origWords = new Set(origText.split(/\s+/).map(clean).filter(Boolean));
  const segments = [];
  let runAdded = [];
  let runKept = [];
  const flush = () => {
    if (runKept.length) { segments.push({ text: runKept.join(" "), added: false }); runKept = []; }
    if (runAdded.length) { segments.push({ text: runAdded.join(" "), added: true }); runAdded = []; }
  };
  for (const raw of newText.split(/\s+/)) {
    const key = clean(raw);
    if (key && !origWords.has(key)) {
      if (runKept.length) { segments.push({ text: runKept.join(" "), added: false }); runKept = []; }
      runAdded.push(raw);
    } else {
      if (runAdded.length) { segments.push({ text: runAdded.join(" "), added: true }); runAdded = []; }
      runKept.push(raw);
    }
  }
  flush();
  return segments;
}

/** True when the revision actually changes the prompt. */
export function hasPromptChange(original = "", revised = "") {
  return String(original || "").trim() !== String(revised || "").trim();
}
