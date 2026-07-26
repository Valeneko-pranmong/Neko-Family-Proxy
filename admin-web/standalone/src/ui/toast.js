export function toast(message, tone = "info") {
  const host = document.querySelector("#toast");
  if (!host) return;
  host.className = `toast toast-${tone}`;
  host.textContent = message;
  host.hidden = false;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => {
    host.hidden = true;
  }, 3600);
}
