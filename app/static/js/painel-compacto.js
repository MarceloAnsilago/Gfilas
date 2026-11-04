(() => {
  const eventsUrl = document.currentScript.dataset.eventsUrl;
  const connection = document.getElementById('monitor-connection');
  const setText = (id, value) => { document.getElementById(id).textContent = value; };
  const ticket = value => String(value ?? '').padStart(3, '0');
  const priority = item => item.prioridade === 'preferencial' ? 'Preferencial' : 'Normal';
  let source = null;

  function renderList(id, items, history) {
    const container = document.getElementById(id);
    container.replaceChildren();
    if (!items.length) {
      const empty = document.createElement('p');
      empty.className = 'text-muted mb-0';
      empty.textContent = history ? 'Nenhuma chamada encerrada.' : 'Nenhuma senha aguardando.';
      container.append(empty);
    }
    items.forEach(item => {
      const card = document.createElement('div');
      card.className = 'monitor-item';
      const number = document.createElement('strong');
      number.textContent = ticket(item.senha);
      card.append(number);
      const lines = history
        ? [priority(item), `Guichê ${item.terminal || '—'} · ${item.usuario || 'Sem atendente'}`, item.resposta || '', item.unidade || '']
        : [priority(item), item.unidade || ''];
      lines.forEach(text => {
        const line = document.createElement('div');
        line.className = 'small';
        line.textContent = text;
        card.append(line);
      });
      container.append(card);
    });
  }

  function render(status) {
    const current = status.senha_atual;
    setText('monitor-title', current ? (current.status === 'aberto' ? 'Chamada atual' : 'Última chamada') : 'Aguardando chamada');
    setText('monitor-ticket', current ? ticket(current.senha) : '—');
    setText('monitor-priority', current ? priority(current) : '');
    setText('monitor-counter', current?.terminal || '—');
    setText('monitor-attendant', current?.usuario ? `Atendente: ${current.usuario}` : '');
    setText('monitor-unit', current?.unidade || '');
    renderList('monitor-upcoming', status.proximas_senhas || [], false);
    renderList('monitor-history', status.ultimas_senhas || [], true);
  }

  function disconnect() {
    if (source) { source.close(); source = null; }
  }

  function connect() {
    if (source) return;
    if (!window.EventSource) {
      connection.textContent = 'Atualize o navegador para receber chamadas em tempo real.';
      return;
    }
    source = new EventSource(eventsUrl);
    source.addEventListener('status', event => {
      try {
        render(JSON.parse(event.data));
        connection.textContent = 'Conectado em tempo real';
      } catch (error) {
        connection.textContent = 'Falha ao atualizar o painel.';
        console.error(error);
      }
    });
    source.onerror = () => { connection.textContent = 'Conexão interrompida. Reconectando…'; };
  }

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) { disconnect(); connect(); }
  });
  window.addEventListener('pagehide', disconnect);
  window.addEventListener('pageshow', connect);
  connect();
})();
