import os
import sys
import hashlib
import time
import re
from datetime import datetime
import unicodedata
import pytesseract
import pdfplumber
import pypdfium2
from elasticsearch import Elasticsearch
from tika import parser
from PIL import Image

# Console UTF-8 (Windows safe)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 1º argumento = pasta a indexar
INCOMING_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE_DIR, "incoming")
# 2º argumento opcional = "new_only" (só ficheiros ainda não indexados)
NEW_ONLY = len(sys.argv) > 2 and sys.argv[2] == "new_only"

ES_URL = os.environ.get("ES_URL", "http://localhost:9200")
INDEX = os.environ.get("ES_INDEX", "files")

# Tesseract path (ajusta se necessário)
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESSERACT_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

def ensure_index(es: Elasticsearch, index_name: str):
    # Se o índice já existir, não mexe
    if es.indices.exists(index=index_name):
        return

    settings = {
        "analysis": {
            "tokenizer": {
                "edge_ngram_tokenizer": {
                    "type": "edge_ngram",
                    "min_gram": 3,
                    "max_gram": 20,
                    "token_chars": ["letter", "digit"],
                }
            },
            "analyzer": {
                "edge_analyzer": {
                    "tokenizer": "edge_ngram_tokenizer",
                    "filter": ["lowercase", "asciifolding"],
                }
            },
        }
    }

    mappings = {
        "properties": {
            # Campos especiais para pesquisa parcial
            "texto_edge": {
                "type": "text",
                "analyzer": "edge_analyzer",
                "search_analyzer": "edge_analyzer",
            },
            "filename_edge": {
                "type": "text",
                "analyzer": "edge_analyzer",
                "search_analyzer": "edge_analyzer",
            },
        }
    }

    es.indices.create(index=index_name, settings=settings, mappings=mappings)
    print(f"[INFO] Índice '{index_name}' criado com analyzer edge_ngram.")


es = Elasticsearch(ES_URL)


# ---------------- Utils ----------------
def strip_accents(text: str) -> str:
    if not text:
        return ""
    # Normaliza e remove caracteres de acentuação
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def make_doc_id(path: str) -> str:
    abspath = os.path.abspath(path)
    return hashlib.sha256(abspath.encode("utf-8", errors="ignore")).hexdigest()


def safe_filesize(path: str) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return 0


def ymq_from_date(date_str: str):
    """
    Devolve (ano, mês, trimestre) a partir de strings tipo:
    - YYYY-MM-DD
    - DD/MM/YYYY
    """
    try:
        if re.match(r"^\d{4}[/-]\d{2}[/-]\d{2}$", date_str):
            y, m, d = re.split(r"[/-]", date_str)
        elif re.match(r"^\d{2}[/-]\d{2}[/-]\d{4}$", date_str):
            d, m, y = re.split(r"[/-]", date_str)
        else:
            return None, None, None
        y = int(y)
        m = int(m)
        q = (m - 1) // 3 + 1 if 1 <= m <= 12 else None
        return y, m, q
    except Exception:
        return None, None, None


def normalize_date_for_es(date_str: str) -> str | None:
    """
    Normaliza datas para o formato ISO aceito pelo Elasticsearch: YYYY-MM-DD.

    Aceita:
    - YYYY-MM-DD ou YYYY/MM/DD
    - DD-MM-YYYY ou DD/MM/YYYY
    """
    try:
        s = date_str.strip()
        # 2024-09-01 ou 2024/09/01
        if re.match(r"^\d{4}[/-]\d{2}[/-]\d{2}$", s):
            y, m, d = re.split(r"[/-]", s)
        # 01-09-2024 ou 01/09/2024
        elif re.match(r"^\d{2}[/-]\d{2}[/-]\d{4}$", s):
            d, m, y = re.split(r"[/-]", s)
        else:
            return None

        y = int(y)
        m = int(m)
        d = int(d)
        return f"{y:04d}-{m:02d}-{d:02d}"
    except Exception:
        return None


# ---------------- Extraction ----------------
def extract_text_with_tika(path):
    try:
        parsed = parser.from_file(path, serverEndpoint="http://localhost:9998/tika")
        return (parsed.get("content", "") or "").strip()
    except Exception as e:
        print(f"[WARN] Tika falhou para {path}: {e}")
        return ""


def tesseract_text(pil_img):
    gray = pil_img.convert("L")
    return pytesseract.image_to_string(
        gray,
        lang="por+eng",
        config="--oem 3 --psm 6 --dpi 300",
    ).strip()


def ocr_pdf(path):
    text = ""
    try:
        # 1) tentar texto nativo com pdfplumber
        with pdfplumber.open(path) as pdf:
            native = "\n".join(page.extract_text() or "" for page in pdf.pages)
        if native.strip():
            return native, "pdfplumber", len(native) / 10000.0  # métrica fake

        # 2) se não houver texto, fazer OCR página a página
        pdf_doc = pypdfium2.PdfDocument(path)
        for page in pdf_doc:
            pil = page.render(scale=2.0).to_pil()
            text += "\n" + tesseract_text(pil)
        if text.strip():
            print("[OCR] Texto extraído via Tesseract:", os.path.basename(path))
        return text.strip(), "tesseract", None
    except Exception as e:
        print(f"[WARN] OCR PDF falhou para {path}: {e}")
        return "", "tesseract", None


def ocr_image(path):
    try:
        image = Image.open(path)
        text = tesseract_text(image)
        if text:
            print("[OCR] Texto extraído de", os.path.basename(path))
        return text.strip(), "tesseract", None
    except Exception as e:
        print(f"[WARN] OCR de imagem falhou para {path}: {e}")
        return "", "tesseract", None


def extract_pdf_text_plain(path):
    """
    Devolve (texto, engine, nº páginas, conf_aprox)
    Tenta: pdfplumber -> Tika -> OCR
    """
    pages = 0

    # a) pdfplumber (texto nativo)
    try:
        with pdfplumber.open(path) as pdf:
            pages = len(pdf.pages)
            parts = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                t = re.sub(r"[ \t]+", " ", t)
                parts.append(t.strip())
            text = "\n\n".join(p for p in parts if p).strip()
            if len(text) > 40:
                return text, "pdfplumber", pages, len(text) / 10000.0
    except Exception as e:
        print(f"[WARN] pdfplumber falhou para {path}: {e}")

    # b) Tika
    try:
        t2 = extract_text_with_tika(path)
        if len(t2) > 40:
            return t2, "tika", pages or None, len(t2) / 10000.0
    except Exception:
        pass

    # c) OCR
    t3, engine, conf = ocr_pdf(path)
    return t3, engine, pages or None, conf


# ---------------- Entities ----------------
def extract_entities(text):
    entities = {}

    # NIFs
    nif_matches = re.findall(r"\b([1235689]\d{8})\b", text)
    if nif_matches:
        entities["nif"] = nif_matches[0]
        if len(nif_matches) > 1:
            entities["client_nif"] = nif_matches[1]

    # IBAN
    iban_match = re.search(r"\bPT50[0-9A-Z]{21}\b", text, re.I)
    if iban_match:
        entities["iban"] = iban_match.group(0)

    # Datas
    date_patterns = [
        r"\b(\d{2}[\/\-.]\d{2}[\/\-.]\d{4})\b",
        r"\b(\d{4}[\/\-.]\d{2}[\/\-.]\d{2})\b",
    ]
    for pattern in date_patterns:
        date_match = re.search(pattern, text)
        if date_match:
            entities["date"] = date_match.group(1)
            break

    # Valores (totais)
    total_patterns = [
        r"Total[:\s]+[€]?\s*(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})",
        r"(?:Valor|Montante)[:\s]+[€]?\s*(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})",
        r"(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})\s*€",
    ]
    found_totals = []
    for pattern in total_patterns:
        matches = re.findall(pattern, text, re.I)
        for match in matches:
            try:
                normalized = match.replace(".", "").replace(",", ".")
                value = float(normalized)
                if value > 0:
                    found_totals.append(value)
            except Exception:
                pass
    if found_totals:
        entities["total"] = max(found_totals)

    # Nº de fatura
    invoice_patterns = [
        r"Fatura\s*(?:n\.?|nº|#)\s*([A-Za-z0-9\-\/]+)",
        r"(?:FT|FA|FR|NC|ND)[:\s\/-]*(\d{4}[\/-]\d+)",
        r"(?:Invoice|Doc)[:\s]*([A-Za-z0-9\-\/]+)",
    ]
    for pattern in invoice_patterns:
        inv_match = re.search(pattern, text, re.I)
        if inv_match:
            entities["invoice_no"] = inv_match.group(1).strip()
            break

    # Moeda
    if "€" in text or re.search(r"\bEUR\b", text, re.I):
        entities["currency"] = "EUR"

    # IVA, base, imposto (heurístico)
    m = re.search(r"\bIVA\b[^\n]*?(\d{1,2}[.,]?\d{0,2})\s*%?", text, re.I)
    if m:
        try:
            entities["iva_rate"] = float(m.group(1).replace(",", "."))
        except Exception:
            pass

    m = re.search(r"(Base|Subtotal)[^\n]*?(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})", text, re.I)
    if m:
        try:
            entities["total_without_tax"] = float(
                m.group(2).replace(".", "").replace(",", ".")
            )
        except Exception:
            pass

    m = re.search(r"(IVA|Imposto)[^\n]*?(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})", text, re.I)
    if m:
        try:
            entities["tax_amount"] = float(
                m.group(2).replace(".", "").replace(",", ".")
            )
        except Exception:
            pass

    # Fornecedor / Cliente (simples)
    ms = re.search(r"Fornecedor[:\s]+(.+)", text, re.I)
    if ms:
        entities["supplier"] = ms.group(1).strip()
    mc = re.search(r"Cliente[:\s]+(.+)", text, re.I)
    if mc:
        entities["client"] = mc.group(1).strip()

    return entities


# ---------------- Index ----------------
def index_file(path):
    t0 = time.perf_counter()
    fid = make_doc_id(path)
    ext = os.path.splitext(path)[1].lower()
    texto = ""
    pages = None
    engine = None
    conf = None

    # Se estiver em modo "só novos" e o ID já existir, salta
    if NEW_ONLY:
        try:
            if es.exists(index=INDEX, id=fid):
                print("SKIP (já indexado):", os.path.basename(path))
                return
        except Exception as e:
            print(f"[WARN] Falha ao verificar existencia em ES para {path}: {e}")

    # Extração de texto
    if ext == ".pdf":
        texto, engine, pages, conf = extract_pdf_text_plain(path)
    elif ext in [".png", ".jpg", ".jpeg", ".tiff", ".tif"]:
        texto = extract_text_with_tika(path)
        engine = "tika"
        if not texto.strip():
            texto, engine, conf = ocr_image(path)
    else:
        texto = extract_text_with_tika(path)
        engine = "tika"

    entities = extract_entities(texto or "")

    # --- NORMALIZAR DATA PARA ELASTICSEARCH ---
    norm_date = None
    if entities.get("date"):
        norm_date = normalize_date_for_es(entities["date"])
        if norm_date:
            entities["date"] = norm_date
        else:
            # Se não conseguirmos normalizar, removemos a data para não rebentar o índice
            print(f"[WARN] Data não reconhecida em {os.path.basename(path)}: {entities['date']!r}")
            entities.pop("date", None)

    # Analítico a partir da data
    if entities.get("date"):
        y, m, q = ymq_from_date(entities["date"])
    else:
        y, m, q = None, None, None

    # Palavra-chave simples do fornecedor (primeira palavra, sem grande lógica)
    supplier_kw = None
    if entities.get("supplier"):
        supplier_kw = entities["supplier"].split(",")[0].split(" ")[0][:40]

    processing_ms = int((time.perf_counter() - t0) * 1000)

    filename = os.path.basename(path)
    texto_final = texto or ""

    doc = {
        "id": fid,
        "filename": filename,
        "filename_edge": filename,   # para n-grams no nome do ficheiro
        "extension": ext.replace(".", ""),
        "path": os.path.abspath(path),
        "texto": texto_final,
        "texto_edge": texto_final,   # para n-grams no texto completo
        "entities": entities,
        "language": "pt",
        "indexed_at": datetime.utcnow().isoformat(),
        # Documental
        "pages": pages,
        "file_size": safe_filesize(path),
        "checksum": fid,
        "source_system": None,
        "document_type": "Fatura"
        if re.search(r"\bFatura\b", texto_final or "", re.I)
        else None,
        # Processo
        "ocr_engine": engine,
        "ocr_confidence": conf,
        "processing_time_ms": processing_ms,
        "error_log": None,
        # Analítico
        "year": y,
        "month": m,
        "quarter": q,
        "supplier_keyword": supplier_kw,
        "category": None,
    }



    try:
        es.index(index=INDEX, id=fid, document=doc)
        print("INDEXED:", os.path.basename(path))
        if entities:
            print(
                "   Entidades:",
                ", ".join([f"{k}={v}" for k, v in entities.items() if v]),
            )
    except Exception as e:
        print(f"[ERROR] Falhou ao indexar {path}: {e}")


def walk_and_index(folder):
    supported = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".xlsx", ".xls"]
    count = 0
    for root, _, files in os.walk(folder):
        for f in files:
            if any(f.lower().endswith(ext) for ext in supported):
                full = os.path.join(root, f)
                index_file(full)
                count += 1
    return count


if __name__ == "__main__":
    print("=" * 60)
    print("DocSearch PT - Indexação (TEXTO + metadados enriquecidos)")
    print("=" * 60)
    print("Pasta:", INCOMING_DIR)
    print("Somente novos:", "SIM" if NEW_ONLY else "NÃO")
    print("Elasticsearch:", ES_URL)
    print("Índice:", INDEX)
    print("=" * 60)

    ensure_index(es, INDEX)

    if not os.path.exists(INCOMING_DIR):
        print(f"[ERROR] Pasta {INCOMING_DIR} não encontrada.")
        sys.exit(1)

    total = walk_and_index(INCOMING_DIR)

    print("=" * 60)
    print(f"Indexação concluída! Total: {total} documento(s)")
    print("=" * 60)
