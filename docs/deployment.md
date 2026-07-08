# Deployment

## Single-server production layout (recommended)

```
/opt/thesislogic/
├── app/              # git checkout (this repo)
├── venv/             # python virtualenv
├── data/             # app.sqlite3, uploads, audit  ← back this up
├── packs/            # your jurisdiction packs      ← back this up
└── thesislogic.env   # environment file
```

```bash
sudo useradd -r -m -d /opt/thesislogic thesislogic
sudo -u thesislogic git clone https://github.com/alentra-dev/thesislogic /opt/thesislogic/app
sudo -u thesislogic python3 -m venv /opt/thesislogic/venv
sudo -u thesislogic /opt/thesislogic/venv/bin/pip install -e /opt/thesislogic/app
sudo apt install poppler-utils ocrmypdf tesseract-ocr   # PDF/OCR intake
```

`/opt/thesislogic/thesislogic.env`:

```bash
THESISLOGIC_DATA_DIR=/opt/thesislogic/data
THESISLOGIC_PACKS_DIR=/opt/thesislogic/packs
THESISLOGIC_ACTIVE_PACK=missouri
THESISLOGIC_HOST=127.0.0.1
THESISLOGIC_PORT=8600
THESISLOGIC_FIRM_NAME=Smith & Jones LLP
THESISLOGIC_ALLOW_REGISTRATION=false          # admins create users via CLI

# local AI posture (see below) — or anthropic / none
THESISLOGIC_GENERATION_PROVIDER=openai_compatible
THESISLOGIC_GENERATION_BASE_URL=http://127.0.0.1:8080
THESISLOGIC_GENERATION_MODEL=your-model
THESISLOGIC_EMBEDDING_PROVIDER=openai_compatible
THESISLOGIC_EMBEDDING_BASE_URL=http://127.0.0.1:8092
```

Install the systemd unit from `deploy/systemd/thesislogic.service`, then:

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now thesislogic
```

## Local AI backends

Any OpenAI-compatible server works. Two common choices:

**llama.cpp** (best for dedicated hardware / AMD+Vulkan/ROCm boxes):

```bash
llama-server -m model.gguf --port 8080 --ctx-size 16384 -np 2         # generation
llama-server -m embedding-model.gguf --port 8092 --embedding          # embeddings
```

**Ollama** (easiest):

```bash
ollama serve   # THESISLOGIC_GENERATION_BASE_URL=http://127.0.0.1:11434
```

Sizing guidance: a 20–30B-parameter instruct model in Q4–Q6 quantization on a 64–128 GB
unified-memory box comfortably serves a small firm. Start conservative; the proof gate makes
model quality a latency/fluency question, not a correctness one.

## Cloud AI (Anthropic, OpenAI, or Google Gemini)

**Anthropic (Claude)** — uses the official SDK (optional extra):

```bash
pip install 'thesislogic[anthropic]'
export THESISLOGIC_GENERATION_PROVIDER=anthropic
export THESISLOGIC_GENERATION_MODEL=claude-opus-4-8     # default
export ANTHROPIC_API_KEY=...
```

**OpenAI** — no extra package (plain HTTPS):

```bash
export THESISLOGIC_GENERATION_PROVIDER=openai
export THESISLOGIC_GENERATION_MODEL=gpt-4o              # default; set your preferred model
export OPENAI_API_KEY=...                               # or THESISLOGIC_GENERATION_API_KEY
```

OpenAI can also serve embeddings: `THESISLOGIC_EMBEDDING_PROVIDER=openai`
(default model `text-embedding-3-small`).

**Google Gemini** — no extra package (plain HTTPS):

```bash
export THESISLOGIC_GENERATION_PROVIDER=gemini
export THESISLOGIC_GENERATION_MODEL=gemini-2.5-pro      # default
export GEMINI_API_KEY=...                               # or GOOGLE_API_KEY / THESISLOGIC_GENERATION_API_KEY
```

Run `thesislogic doctor` after configuring any provider — it performs a live health probe
against the vendor API before attorneys ever see the deployment.

Whichever vendor you choose, the safety posture is identical: the proof gate, the
retrieval-confidence floor, and the audit trail treat every model as untrusted. Review your
professional-responsibility obligations for confidentiality and your provider's data-processing
terms before sending client material to any cloud API. Shadow mode
(`THESISLOGIC_PREFER_LIVE_OUTPUT=false`) lets you evaluate cloud output without it ever reaching
an attorney-facing answer.

## HTTPS / reverse proxy

Bind the app to localhost and front it with nginx/caddy for TLS:

```nginx
server {
    listen 443 ssl;
    server_name thesislogic.yourfirm.example;
    client_max_body_size 100M;
    location / { proxy_pass http://127.0.0.1:8600; }
}
```

## Backups

Back up `data/` and `packs/` (both are plain files + SQLite). The authority index can always be
rebuilt from `authorities.ndjson`, so the NDJSON sources are the critical pack artifact.

## Upgrades

```bash
cd /opt/thesislogic/app && sudo -u thesislogic git pull
sudo -u thesislogic /opt/thesislogic/venv/bin/pip install -e .
sudo systemctl restart thesislogic
```
