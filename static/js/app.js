// O HTMX não troca o conteúdo em respostas de erro; sem isso, a falha passaria despercebida.
(function () {
  function showError(message) {
    let toast = document.getElementById("error-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "error-toast";
      toast.className = "toast";
      toast.setAttribute("role", "alert");
      document.body.append(toast);
    }
    toast.textContent = message;
    clearTimeout(toast.hideTimer);
    toast.hideTimer = setTimeout(() => toast.remove(), 6000);
  }

  document.addEventListener("htmx:responseError", () => {
    showError("Algo deu errado. Recarregue a página e tente novamente.");
  });
  document.addEventListener("htmx:sendError", () => {
    showError("Sem conexão com o servidor. Tente novamente.");
  });
})();
