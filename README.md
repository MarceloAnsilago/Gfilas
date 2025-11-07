@'
# Gfilas

Painel Flask (Fly.io)

## Rodar local
python -m venv venv
venv\Scripts\activate
pip install -r requirements.prod.txt
set FLASK_ENV=development
copy .env.example .env  # edite valores
python -m flask run

## Deploy (Fly.io)
flyctl deploy -a senhasflask
'@ | Out-File -Encoding UTF8 .\README.md

git add README.md
git commit -m "docs: add README"
git push
