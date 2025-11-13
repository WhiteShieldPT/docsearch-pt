# 📄 DocSearch PT

**Intelligent Document Search with OCR + Elasticsearch + FastAPI**

DocSearch PT is a local application for advanced document indexing and
search (PDF, images, and Excel) with OCR, automatic entity extraction,
and a modern interface.

It works **100% locally**, ideal for accounting firms, offices,
consultants, and teams who need to find documents quickly and securely.

------------------------------------------------------------------------

## 🚀 Features

### 🔍 Smart Universal Search

-   Search by:
    -   Name\
    -   Tax Number (NIF)\
    -   IBAN\
    -   Invoice Number\
    -   Dates\
    -   Values (€)\
    -   Free text (OCR)
-   Automatic intent detection\
-   Fuzzy search and exact search options\
-   Highlighted text in results

### 📑 Automatic Entity Extraction

The system extracts: - NIF (supplier and client)\
- Invoice number\
- IBAN\
- Dates (normalized to YYYY-MM-DD)\
- Totals, Base, VAT, tax\
- Currency\
- Number of pages\
- OCR confidence\
- Document type (heuristic)

### 📂 Folder Management

-   Set working folder\
-   Automatic subfolder support\
-   Default folder stored in `config.json`\
-   Automatic counting of local vs indexed documents

### 🔄 Advanced Indexing

-   Full indexing or **only new files**\
-   Real-time progress page with:
    -   Percentage\
    -   Counters\
    -   Log output\
    -   **Cancel indexing**\
-   Remove orphaned documents\
-   Full index reset

### 🧩 Integrated OCR

-   Tesseract (Portuguese + English)\
-   pdfplumber for text PDFs\
-   Tika fallback\
-   Page-by-page OCR for scanned PDFs

### 🌙 Light / Dark Mode

-   Theme toggle\
-   Synced across all pages

------------------------------------------------------------------------

## 📦 Technologies

**Backend:** Python 3.11+, FastAPI, pdfplumber, Tika, Tesseract OCR,
pypdfium2\
**Search Engine:** Elasticsearch 8.x\
**Frontend:** HTML + CSS + Jinja2\
**Runtime:** Uvicorn + subprocess + threaded monitoring

------------------------------------------------------------------------

## 📜 Project Structure

    docsearch_pt_ready/
    │
    ├── app.py             # FastAPI server + UI + indexing system
    ├── ingest.py          # OCR/extraction engine + ES indexing
    │
    ├── index.html         # Main search page
    ├── progress.html      # Indexing progress UI
    ├── settings.html      # Settings and maintenance tools
    │
    ├── config.json        # Stores default folder
    ├── incoming/          # Initial document folder
    └── static/            # Static assets (if any)

------------------------------------------------------------------------

## 🛠️ Installation

### 1️⃣ Install Python dependencies

``` sh
pip install -r requirements.txt
```

### 2️⃣ Install Tesseract OCR

Windows Installer:\
https://github.com/UB-Mannheim/tesseract/wiki

Verify the default path:

    C:\Program Files\Tesseract-OCR  esseract.exe

### 3️⃣ Start Elasticsearch

Either ZIP or Docker.

### 4️⃣ Start Tika Server

``` sh
java -jar tika-server.jar --port 9998
```

### 5️⃣ Run the App

``` sh
python app.py
```

Open in browser:\
👉 http://127.0.0.1:8000

------------------------------------------------------------------------

## 🔄 How Indexing Works

1.  Choose your folder\
2.  Click **Reindex documents**\
3.  A `task_id` is created\
4.  The progress page shows:
    -   Percentage\
    -   File count\
    -   Logs\
    -   **Cancel button**

Indexing runs in a separate subprocess and can be canceled anytime.

------------------------------------------------------------------------

## 🧹 Index Maintenance

Available in **Settings**:

-   🧩 Remove missing/orphan files\
-   🔄 Reset index\
-   📁 Change default folder\
-   📊 View statistics

------------------------------------------------------------------------

## 📄 Supported File Types

  Type       Supported   Method
  ---------- ----------- -------------------------
  PDF        ✔           pdfplumber / Tika / OCR
  PNG        ✔           OCR
  JPG/JPEG   ✔           OCR
  TIFF       ✔           OCR
  XLS/XLSX   ✔           Tika

------------------------------------------------------------------------

## 🔍 Search Examples

  Search           Result
  ---------------- ----------------------
  `504321987`      NIF match
  `FT 2024/1005`   Invoice number
  `meta lda`       Supplier/client name
  `120.50`         Total amount
  `2023-05-10`     Date
  `energy`         Text inside PDFs

------------------------------------------------------------------------

## 🎯 Project Goal

Provide a **fast, local, privacy‑friendly** tool for intelligent
document search --- without relying on cloud services.

------------------------------------------------------------------------

Need badges, screenshots, or an improved layout?\
Just ask!
