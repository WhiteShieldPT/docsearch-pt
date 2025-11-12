docsearch_pt_ready/
│
├── app.py
├── ingest.py
├── config.json
├── requirements.txt
├── README.md
├── .gitignore
│
├── incoming/            ← onde colocas os ficheiros a indexar
├── templates/
│   ├── index.html
│   ├── progress.html
│   └── settings.html
└── static/

# --- Framework Web ---
fastapi
uvicorn
jinja2
python-multipart

# --- Pesquisa / Base de dados ---
elasticsearch

# --- Extração e OCR ---
pdfplumber
pypdfium2
pytesseract
pillow

# --- Utilitários ---
unicodedata2  # normalização de texto (opcional)


# 📄 DocSearch PT Ready

Sistema de indexação e pesquisa de documentos com OCR e metadados — 100% Python + Elasticsearch + Tesseract.

---

## 🚀 Funcionalidades
- Interface web (FastAPI + Jinja2)
- Extração automática de texto de PDFs e imagens
- OCR com Tesseract
- Indexação e pesquisa full-text com Elasticsearch
- Extração automática de NIF, IBAN, datas, totais, número de fatura, fornecedor e cliente

---

## ⚙️ Requisitos

### 🔹 Sistema
- **Python 3.11+**
- **Elasticsearch 8.x**  
  (instalar ou usar via Docker)
- **Tesseract OCR**  
  (Windows: [tesseract-ocr.github.io/tessdoc/Downloads](https://tesseract-ocr.github.io/tessdoc/Downloads))

### 🔹 Bibliotecas Python
Instala todas com:
```bash
pip install -r requirements.txt
