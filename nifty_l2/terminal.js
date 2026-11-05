"use strict";
document.addEventListener("click", async function(event) {
  const button = event.target.closest("#copy-snapshots");
  if (!button) return;
  const status = document.querySelector("#copy-status");
  if (status) status.textContent = "Preparing export…";
  try {
    const url = button.getAttribute("data-export-url");
    if (!url || !url.startsWith("/export?")) throw new Error("Invalid export route");
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) throw new Error("Export failed");
    const value = await response.text();
    if (!value.trim()) throw new Error("No table data");
    await navigator.clipboard.writeText(value);
    if (status) status.textContent = "Copied saved table to clipboard";
  } catch (_error) {
    if (status) status.textContent = "Clipboard unavailable: use Export TXT";
  }
});
