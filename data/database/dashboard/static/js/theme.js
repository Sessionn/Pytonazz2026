// Applica il tema salvato prima del primo paint (evita il flash chiaro/scuro).
(function () {
  var theme = null;
  try {
    theme = localStorage.getItem("theme");
  } catch (_) {}
  if (theme !== "light" && theme !== "dark") {
    theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  document.documentElement.setAttribute("data-theme", theme);
})();
