# Gfilas

Painel de senhas em Flask com painel digital, preparado para rodar localmente e em Fly.io com banco SQLite persistente.

## Variaveis de ambiente

- `SECRET_KEY`: chave do Flask usada para sessoes. Troque por um valor longo e secreto.
- `PAINEL_DB_PATH`: caminho para o arquivo SQLite (`ultima_senha.db` por padrao; o deploy em Fly.io aponta para `/data/ultima_senha.db`).
- `PAINEL_UNIDADE_PADRAO`: rotulo exibido quando nenhum nome de unidade e informado.
- `PAINEL_USUARIO_PADRAO`: usuario exibido quando o operador nao for informado.
- `PAINEL_FUSO_HORARIO`: fuso usado nos carimbos de data/hora (`America/Sao_Paulo`, `Etc/GMT+3`, etc.).
- `PAINEL_MAX_ULTIMAS`: quantas senhas encerradas aparecem no painel digital.
- `PAINEL_VIDEO_URL`, `PAINEL_VIDEO_MUTED`, `PAINEL_YT_PLAYLIST_URL`, `PAINEL_YT_PLAYLIST_ID`, `PAINEL_YT_MUTED`: parametros opcionais para o conteudo em tela cheia do painel.
- `THERMAL_PRINTER_MODE`, `THERMAL_PRINTER_ENABLED`, `THERMAL_PRINTER_NAME`, `THERMAL_PRINTER_ENCODING`, `THERMAL_PRINTER_LINE_ENDING`, `THERMAL_PRINTER_CODEPAGE_COMMAND`, `THERMAL_PRINTER_CUT`, `THERMAL_PRINTER_DATATYPE`, `THERMAL_PRINTER_PROTOCOL`, `THERMAL_PRINTER_RASTER_WIDTH`: configuracoes da impressora termica no Windows via `win32print`.
- `PRINT_AGENT_BASE_URL`, `PRINT_AGENT_TOKEN`, `PRINT_AGENT_POLL_INTERVAL`: configuracoes do agente local de impressao usado quando o servidor principal roda no Fly.io.
- `BASE_URL`, `PANEL_URL`, `POLL_INTERVAL`, `OPEN_PANEL`, `BROWSER_MODE`: configuracoes opcionais do executavel `Painel.exe`.

Um exemplo de todas as variaveis acima esta em `.env.example`.

## Rodar local

1. Crie o ambiente virtual: `python -m venv venv`.
2. Ative o ambiente (`venv\Scripts\activate` no Windows, `source venv/bin/activate` no macOS/Linux).
3. Instale as dependencias: `pip install -r requirements.prod.txt`.
4. Copie o exemplo de configuracao: `copy .env.example .env` (Windows) ou `cp .env.example .env` (macOS/Linux) e ajuste as variaveis conforme o ambiente.
5. (Opcional) `set FLASK_ENV=development` (Windows) ou `export FLASK_ENV=development` (macOS/Linux).
6. Execute `python -m flask run --app run.py --debug` (ou `python run.py`) para subir o servidor em `http://localhost:5000`.

O SQLite (`ultima_senha.db`) e criado automaticamente quando o aplicativo inicia.

## Deploy (Fly.io)

1. Instale e autentique-se no `flyctl`.
2. Execute `flyctl deploy -a senhasflask`; o `Dockerfile` utiliza `requirements.deploy.txt` para instalar somente o necessario em producao.
3. O `fly.toml` ja configura o volume `/data` (montado como `app_data`) e define `PAINEL_DB_PATH=/data/ultima_senha.db` para manter o SQLite persistente.
4. Para ver logs ou diagnosticar problemas, use `flyctl logs -a senhasflask` e ajuste variaveis via `flyctl secrets` ou pelo painel da Fly.

## Modo recomendado no Fly.io

Quando o sistema principal roda no Fly.io, a impressora USB do Windows nao fica visivel ao servidor. O modo recomendado e:

1. No Fly.io, configure:
   `THERMAL_PRINTER_MODE=queue`
   `PRINT_AGENT_TOKEN=<token-longo>`
2. No celular, abra `/senhas` para gerar senha normal ou preferencial.
3. No PC da recepcao, instale apenas o driver da impressora e execute `Painel.exe`.

O servidor web passa a enfileirar cada impressao e o `Painel.exe` busca os jobs pendentes para imprimir localmente com `win32print`, sem usar `window.print()`.

## Painel.exe

O novo modo desktop abre o painel e roda o agente de impressao no mesmo processo Windows. O comportamento principal e:

- abre `/painel` em janela dedicada do Edge/Chrome com `X` para fechar, ou em modo kiosk se voce escolher isso explicitamente;
- consulta `POST /print-agent/jobs/claim`;
- imprime localmente via ESC/POS USB;
- marca o job como `completed` ou `error`;
- grava log em `logs/painel.log`;
- impede multiplas instancias simultaneas no mesmo PC.

### Configuracao do PC

Copie [painel_config.example.json](/d:/driver/Documentos/SenhasFlask/painel_config.example.json) para `painel_config.json` ao lado do executavel e ajuste:

```json
{
  "BASE_URL": "https://senhasflask.fly.dev",
  "PRINT_AGENT_TOKEN": "coloque-o-token-aqui",
  "THERMAL_PRINTER_NAME": "POS58 DRIVER (TESTADO)",
  "THERMAL_PRINTER_ENCODING": "cp850",
  "THERMAL_PRINTER_LINE_ENDING": "crlf",
  "THERMAL_PRINTER_CUT": false,
  "THERMAL_PRINTER_DATATYPE": "RAW",
  "THERMAL_PRINTER_PROTOCOL": "escpos_raster",
  "THERMAL_PRINTER_RASTER_WIDTH": 384,
  "POLL_INTERVAL": 1.0,
  "OPEN_PANEL": true,
  "PANEL_URL": "https://senhasflask.fly.dev/painel",
  "BROWSER_MODE": "edge_app"
}
```

Campos aceitos:

- `BASE_URL`: URL base do app no Fly.io.
- `PRINT_AGENT_TOKEN`: mesmo token configurado no servidor.
- `THERMAL_PRINTER_NAME`: nome da impressora no Windows.
- `THERMAL_PRINTER_ENCODING`: encoding ESC/POS, por padrao `cp850`.
- `THERMAL_PRINTER_LINE_ENDING`: use `crlf` por padrao; se a impressora preferir, troque para `lf`.
- `THERMAL_PRINTER_CODEPAGE_COMMAND`: envia `ESC t n` apenas se voce informar explicitamente um valor como `2`.
- `THERMAL_PRINTER_CUT`: habilita o comando de corte; por padrao fica desligado para evitar papel em branco em modelos simples.
- `THERMAL_PRINTER_DATATYPE`: `RAW` para ESC/POS bruto ou `TEXT` para compatibilidade com drivers Windows.
- `THERMAL_PRINTER_PROTOCOL`: `escpos_raster` para mandar a imagem já rasterizada em bytes ESC/POS, `bitmap` para desenhar via driver Windows, `gdi_text` para texto via GDI, `text` para texto simples ou `escpos` para comandos ESC/POS. Se o modelo imprimir em branco, deixe `escpos_raster` como primeira tentativa.
- `THERMAL_PRINTER_RASTER_WIDTH`: largura em pixels do cupom rasterizado, normalmente `384` para papel 58 mm.
- `POLL_INTERVAL`: intervalo de polling em segundos.
- `OPEN_PANEL`: se `true`, abre o painel visual; se `false`, roda apenas o agente.
- `PANEL_URL`: URL exata do painel, normalmente `<BASE_URL>/painel`.
- `BROWSER_MODE`: `edge_app` (padrao, com `X`), `edge_kiosk`, `chrome_app`, `chrome_kiosk` ou `pywebview`.

Tambem e possivel usar `.env` com as mesmas chaves, mas `painel_config.json` tem prioridade.

### Gerar o executavel

1. Crie o ambiente virtual: `python -m venv venv`
2. Instale as dependencias ou rode direto o script de build.
3. Execute `build_painel_exe.bat`
4. O executavel final sera gerado em `dist\Painel.exe`

O script instala `PyInstaller` e empacota `desktop_panel.py` como um unico executavel Windows.

## Impressao remota via agente legado

Quando o sistema principal roda no Fly.io, a impressora USB do Windows nao fica visivel ao servidor. Para esse caso:

1. No Fly.io, configure:
   `THERMAL_PRINTER_MODE=queue`
   `PRINT_AGENT_TOKEN=<token-longo>`
2. No PC Windows da impressora, use um `.env` local com:
   `THERMAL_PRINTER_MODE=local`
   `THERMAL_PRINTER_NAME=POS58 DRIVER (TESTADO)` (ou o nome real no Windows)
   `PRINT_AGENT_BASE_URL=https://SEU-APP.fly.dev`
   `PRINT_AGENT_TOKEN=<mesmo-token-do-fly>`
3. Inicie o agente no PC da impressora:
   `python print_agent.py`

O servidor web passa a enfileirar as impressoes e o agente busca cada job pendente para imprimir localmente com `win32print`.

## Observacoes

- O repositorio tambem inclui scripts Windows (`bootstrap_venv.bat`, `start_server.bat`) para facilitar o bootstrap em estacoes Windows.
- Use `requirements.prod.txt` no ambiente local e mantenha `requirements.deploy.txt` alinhado ao que sera instalado dentro do container.
- A tela `/senhas` pode imprimir direto no Windows (`THERMAL_PRINTER_MODE=local`) ou enfileirar para um agente local (`THERMAL_PRINTER_MODE=queue`).
- Rotas de impressao: `POST /senhas/imprimir/normal`, `POST /senhas/imprimir/preferencial` e `POST /senhas/imprimir/teste`.
- `print_agent.py` continua disponivel como fallback; o modo recomendado agora e `Painel.exe`.
