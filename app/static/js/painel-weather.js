(() => {
  const INTERVAL = 30 * 60 * 1000;
  const CACHE_KEY = 'gfilas-weather-sao-miguel-v1';
  const url = 'https://api.open-meteo.com/v1/forecast?' + new URLSearchParams({
    latitude: '-11.69361', longitude: '-62.71139',
    current: 'temperature_2m,weather_code,wind_speed_10m,wind_direction_10m,is_day',
    daily: 'temperature_2m_max,temperature_2m_min',
    timezone: 'America/Porto_Velho', forecast_days: '1', wind_speed_unit: 'kmh',
  });
  let cached = null;
  let timer;
  let loading = false;

  function valid(data) {
    return data && ['temperature', 'max', 'min', 'wind', 'direction', 'code', 'isDay', 'fetchedAt'].every(key =>
      typeof data[key] === 'number' && Number.isFinite(data[key]));
  }

  function condition(code, day) {
    if (code === 0) return [day ? '☀️' : '🌙', day ? 'Céu limpo' : 'Noite de céu limpo'];
    if (code === 1 || code === 2) return [day ? '🌤️' : '☁️', 'Parcialmente nublado'];
    if (code === 3) return ['☁️', 'Nublado'];
    if (code === 45 || code === 48) return ['🌫️', 'Nevoeiro'];
    if ([51, 53, 55, 56, 57].includes(code)) return ['🌦️', 'Garoa'];
    if ([61, 63, 65, 66, 67, 80, 81, 82].includes(code)) return ['🌧️', 'Chuva'];
    if ([71, 73, 75, 77, 85, 86].includes(code)) return ['🌨️', 'Neve'];
    if ([95, 96, 99].includes(code)) return ['⛈️', 'Trovoadas'];
    return ['☁️', 'Condição não informada'];
  }

  function render(data, stale = false) {
    const set = (id, text) => { document.getElementById(id).textContent = text; };
    const [icon, description] = condition(data.code, data.isDay);
    set('weather-icon', icon);
    set('weather-description', description);
    set('weather-temperature', `${Math.round(data.temperature)}°`);
    set('weather-max', `${Math.round(data.max)}°`);
    set('weather-min', `${Math.round(data.min)}°`);
    set('weather-wind', `${Math.round(data.wind)} km/h`);
    const directions = ['N', 'NE', 'L', 'SE', 'S', 'SO', 'O', 'NO'];
    set('weather-direction', `Vento ${directions[Math.round(data.direction / 45) % 8]}`);
    const time = new Date(data.fetchedAt).toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit', timeZone: 'America/Porto_Velho'});
    set('weather-update', stale ? `Sem conexão · dados de ${time}` : `Atualizado às ${time} · a cada 30 min`);
  }

  async function update() {
    if (loading) return;
    clearTimeout(timer);
    if (cached && Date.now() - cached.fetchedAt >= 0 && Date.now() - cached.fetchedAt < INTERVAL) {
      render(cached);
      timer = setTimeout(update, INTERVAL - (Date.now() - cached.fetchedAt));
      return;
    }
    loading = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(url, {signal: controller.signal});
      if (!response.ok) throw new Error('Weather request failed');
      const payload = await response.json();
      const current = payload.current;
      const data = {temperature: current?.temperature_2m, code: current?.weather_code,
        wind: current?.wind_speed_10m, direction: current?.wind_direction_10m, isDay: current?.is_day,
        max: payload.daily?.temperature_2m_max?.[0], min: payload.daily?.temperature_2m_min?.[0], fetchedAt: Date.now()};
      if (!valid(data)) throw new Error('Invalid weather data');
      cached = data;
      try { localStorage.setItem(CACHE_KEY, JSON.stringify(data)); } catch { /* Optional cache. */ }
      render(data);
    } catch {
      if (cached) render(cached, true);
      else {
        document.getElementById('weather-description').textContent = 'Tempo indisponível';
        document.getElementById('weather-update').textContent = 'Sem dados · nova consulta em 30 min';
      }
    } finally {
      clearTimeout(timeout);
      loading = false;
      timer = setTimeout(update, INTERVAL);
    }
  }

  try {
    const saved = JSON.parse(localStorage.getItem(CACHE_KEY));
    if (valid(saved)) cached = saved;
  } catch { /* A missing cache does not prevent the initial request. */ }
  if (cached) render(cached, Date.now() - cached.fetchedAt >= INTERVAL);
  update();
  window.addEventListener('online', update);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) update(); });
})();
