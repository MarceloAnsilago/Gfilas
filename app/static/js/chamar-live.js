(() => {
  const fila = document.getElementById("fila-live");
  const status = document.getElementById("fila-live-status");
  if (!fila || !window.EventSource) return;

  let pending = false;
  let updating = false;
  let stopped = false;
  const controller = new AbortController();
  const url = new URL(window.location.href);
  url.searchParams.set("fragment", "fila");

  async function refresh() {
    pending = true;
    if (updating || stopped) return;
    updating = true;
    try {
      while (pending && !stopped) {
        pending = false;
        const response = await fetch(url, {
          cache: "no-store", signal: controller.signal,
        });
        if (!response.ok) throw new Error("Falha ao atualizar a fila.");
        const html = await response.text();
        if (stopped) return;
        fila.innerHTML = html;
        status.textContent = "Fila atualizada automaticamente.";
      }
    } catch (error) {
      if (error.name !== "AbortError") {
        status.textContent = "Nao foi possivel atualizar a fila. Use Atualizar para tentar novamente.";
      }
    } finally {
      updating = false;
    }
  }

  const events = new EventSource("/painel/events");
  events.addEventListener("status", refresh);
  events.onerror = () => {
    status.textContent = "Reconectando a atualizacao automatica da fila...";
  };
  fila.addEventListener("click", (event) => {
    if (event.target.closest("[data-refresh-fila]")) refresh();
  });
  window.addEventListener("pagehide", () => {
    stopped = true;
    events.close();
    controller.abort();
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) window.location.reload();
  });
})();
