document.addEventListener("DOMContentLoaded", () => {
  const params = new URLSearchParams(window.location.search);
  const tab = params.get("tab");
  if (!tab) {
    return;
  }
  document.body.dataset.activeTab = tab;
});
