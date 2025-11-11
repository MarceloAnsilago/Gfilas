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

## Observacoes

- O repositorio tambem inclui scripts Windows (`bootstrap_venv.bat`, `start_server.bat`) para facilitar o bootstrap em estacoes Windows.
- Use `requirements.prod.txt` no ambiente local e mantenha `requirements.deploy.txt` alinhado ao que sera instalado dentro do container.
