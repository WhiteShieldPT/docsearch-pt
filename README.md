#docsearch_pt_ready/
#│
#├── app.py
#├── ingest.py
#├── config.json
#├── requirements.txt
#├── README.md
#├── .gitignore
#│
#├── incoming/            ← onde colocas os ficheiros a indexar
#├── templates/
#│   ├── index.html
#│   ├── progress.html
#│   └── settings.html
#└── static/


# --- Framework Web ---
fastapi
uvicorn
jinja2
python-multipart

# --- Pesquisa / Base de dados ---
elasticsearch

# --- Extração e OCR ---
pytesseract
pdfplumber
pypdfium2
pillow
tika

# --- Suporte a formatação e manipulação ---
unicodedata2

# --- Utilitários do sistema ---
# (usados mas já incluídos na biblioteca padrão do Python)
# os, sys, re, json, threading, subprocess, datetime, hashlib, time, uuid, etc.
