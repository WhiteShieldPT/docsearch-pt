from fastapi.responses import FileResponse, Response, JSONResponse
import mimetypes
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from elasticsearch import Elasticsearch
from elasticsearch.helpers import scan, bulk
from jinja2 import Environment, FileSystemLoader, ChoiceLoader, select_autoescape
import uvicorn
import os
import sys
import subprocess
import uuid
import re
import json
import threading
import unicodedata
from urllib.parse import unquote
from pathlib import Path

ES_URL = os.environ.get("ES_URL", "http://127.0.0.1:9200")
INDEX = os.environ.get("ES_INDEX", "files")

APP_VERSION = "0.1.2.20251111"
WEB_DIR = os.path.dirname(__file__)
BASE_DIR = os.path.abspath(os.path.join(WEB_DIR, os.pardir))
INCOMING_DIR = os.path.join(BASE_DIR, "incoming")

# Configuração da pasta por defeito (persistente em config.json)
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def load_config() -> dict:
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[WARN] Falha ao ler config.json: {e}")
    return {}


def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] Falha ao gravar config.json: {e}")


_config = load_config()
DEFAULT_FOLDER = _config.get("default_folder") or INCOMING_DIR

# Garantir que as pastas existem
os.makedirs(INCOMING_DIR, exist_ok=True)
os.makedirs(DEFAULT_FOLDER, exist_ok=True)

SUPPORTED_EXTS = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".xlsx", ".xls"]

# Dicionário global para armazenar progresso de indexação
indexing_progress = {}

app = FastAPI()

static_dir = os.path.join(WEB_DIR, "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

template_dirs = []
for name in ("templates", "Templates"):
    p = os.path.join(WEB_DIR, name)
    if os.path.isdir(p):
        template_dirs.append(p)
if not template_dirs:
    template_dirs = [WEB_DIR]

env = Environment(
    loader=ChoiceLoader([FileSystemLoader(template_dirs)]),
    autoescape=select_autoescape(),
)

es = Elasticsearch(ES_URL)


# ------------- Helpers -------------
def strip_accents(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _to_float_or_none(s: str):
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None
    try:
        return float(s.replace(",", "."))
    except Exception:
        return None


def _detect_query_type(universal_query: str):
    query = universal_query.strip()
    if re.match(r"^\d{9}$", query):
        return {"type": "nif", "value": query}
    if re.match(r"^PT50[0-9A-Z]{21}$", query, re.I):
        return {"type": "iban", "value": query}
    value_match = re.match(r"^€?\s*(\d+[.,]\d{2})$", query.replace(" ", ""))
    if value_match:
        value = float(value_match.group(1).replace(",", "."))
        return {"type": "total", "value": value}
    if re.match(r"^(FT|FA|FR|F)[\s\-\/]?\d{4}[\/\-]?\d+", query, re.I):
        return {"type": "invoice", "value": query}
    if re.match(r"^[A-Za-zÀ-ÿ\s\.,\&\-]{3,}$", query):
        return {"type": "name", "value": query}
    return {"type": "text", "value": query}


def get_default_folder() -> str:
    """Devolve a pasta por defeito atual (global)."""
    return DEFAULT_FOLDER


def normalize_folder(folder: str | None) -> str:
    """
    Garante que o caminho da pasta fica correto:
    - Se vazio -> pasta por defeito
    - Se absoluto (C:\...) -> devolve tal e qual
    - Se relativo -> junta ao BASE_DIR
    - Corrige / para \ no Windows
    """
    if not folder:
        return get_default_folder()

    f = str(folder).strip().strip('"')

    # Normalizar separadores (caso venham com /)
    f = f.replace("/", os.sep)

    # Se já for absoluto (ex: C:\Users\andre\...)
    if os.path.isabs(f):
        return f

    # Caso contrário, tratar como relativo à pasta do projeto
    return os.path.abspath(os.path.join(BASE_DIR, f))


def count_local_docs(folder: str = None) -> int:
    base = normalize_folder(folder) if folder else get_default_folder()
    if not os.path.exists(base):
        return 0

    total = 0
    for root, _, files in os.walk(base):
        for f in files:
            if any(f.lower().endswith(ext) for ext in SUPPORTED_EXTS):
                total += 1
    return total


def count_indexed_docs(folder: str = None) -> int:
    try:
        if folder:
            base = normalize_folder(folder)
            query = {"prefix": {"path.keyword": base}}
        else:
            query = {"match_all": {}}
        res = es.count(index=INDEX, body={"query": query})
        return int(res.get("count", 0))
    except Exception:
        return 0


def render_home(msg: str = "", **kwargs):
    raw_folder = kwargs.get("current_folder") or kwargs.get("folder") or get_default_folder()
    current_folder = normalize_folder(raw_folder)

    kwargs["current_folder"] = current_folder
    kwargs.setdefault("local_count", count_local_docs(current_folder))
    kwargs.setdefault("indexed_count", count_indexed_docs(current_folder))
    kwargs.setdefault("INDEX", INDEX)
    kwargs.setdefault("APP_VERSION", APP_VERSION)

    template = env.get_template("index.html")
    return template.render(msg=msg, **kwargs)


def get_subfolders(base_path: str) -> list:
    """Retorna lista de subpastas até 2 níveis de profundidade, começando pela pasta base."""
    folders = []
    try:
        base = Path(base_path)
        if not base.exists():
            return folders

        folders.append(str(base))

        # Nível 1
        for item in base.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                folders.append(str(item))
                # Nível 2
                try:
                    for subitem in item.iterdir():
                        if subitem.is_dir() and not subitem.name.startswith("."):
                            folders.append(str(subitem))
                except Exception:
                    pass
    except Exception as e:
        print(f"Erro ao listar pastas: {e}")

    return sorted(folders)


# ------------- Home / pesquisa -------------
@app.get("/", response_class=HTMLResponse)
def home(
    universal: str = "",
    q: str = "",
    nif: str = "",
    date_from: str = "",
    date_to: str = "",
    min_total: str = "",
    max_total: str = "",
    size: int = 50,
    msg: str = "",
    force_text: int = 0,
    folder: str = "",
    exact: int = 0,
):
    min_total_val = _to_float_or_none(min_total)
    max_total_val = _to_float_or_none(max_total)

    # Normalizar pasta atual vinda do formulário/query
    current_folder = normalize_folder(folder)

    must = []
    should = []

    # Filtrar sempre pela pasta atual
    must.append({"prefix": {"path.keyword": current_folder}})

    universal_ascii = strip_accents(universal.lower()) if universal else None

    if universal:
        if force_text:
            # Pesquisa forçada no texto + n-grams
            should.append(
                {
                    "multi_match": {
                        "query": universal,
                        "fields": [
                            "filename^3",
                            "filename_edge^4",   # n-grams no nome
                            "texto^2",
                            "texto_edge^3",      # n-grams no texto
                            "entities.supplier^3",
                            "entities.client^3",
                            "entities.invoice_no^2",
                            "entities.nif^2",
                            "entities.client_nif^2",
                            "entities.iban^2",
                        ],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                    }
                }
            )
        else:
            detection = _detect_query_type(universal)
            if detection["type"] == "nif":
                should.extend(
                    [
                        {"term": {"entities.nif": detection["value"]}},
                        {"term": {"entities.client_nif": detection["value"]}},
                    ]
                )
            elif detection["type"] == "iban":
                must.append({"term": {"entities.iban": detection["value"]}})
            elif detection["type"] == "total":
                must.append(
                    {
                        "range": {
                            "entities.total": {
                                "gte": detection["value"] - 0.01,
                                "lte": detection["value"] + 0.01,
                            }
                        }
                    }
                )
            elif detection["type"] == "invoice":
                should.extend(
                    [
                        {
                            "match": {
                                "entities.invoice_no": {
                                    "query": detection["value"],
                                    "boost": 2,
                                }
                            }
                        },
                        {
                            "wildcard": {
                                "entities.invoice_no": f"*{detection['value']}*"
                            }
                        },
                    ]
                )
            elif detection["type"] == "name":
                if exact:
                    # 🔒 Modo exato: sem n-grams, sem fuzziness
                    should.extend(
                        [
                            {
                                "match_phrase": {
                                    "entities.supplier": {
                                        "query": universal,
                                        "boost": 5,
                                    }
                                }
                            },
                            {
                                "match_phrase": {
                                    "entities.client": {
                                        "query": universal,
                                        "boost": 5,
                                    }
                                }
                            },
                            {
                                "match_phrase": {
                                    "filename": {
                                        "query": universal,
                                        "boost": 3,
                                    }
                                }
                            },
                            {
                                "match_phrase": {
                                    "texto": {
                                        "query": universal,
                                        "boost": 3,
                                    }
                                }
                            },
                        ]
                    )
                else:
                    # 🔍 Modo “Google”: fuzzy + n-grams
                    should.extend(
                        [
                            {
                                "match": {
                                    "entities.supplier": {
                                        "query": universal,
                                        "boost": 3,
                                        "fuzziness": "AUTO",
                                    }
                                }
                            },
                            {
                                "match": {
                                    "entities.client": {
                                        "query": universal,
                                        "boost": 3,
                                        "fuzziness": "AUTO",
                                    }
                                }
                            },
                            {
                                "match": {
                                    "texto": {
                                        "query": universal,
                                        "boost": 1,
                                        "fuzziness": "AUTO",
                                    }
                                }
                            },
                            {
                                "match_phrase": {
                                    "entities.supplier": {"query": universal, "boost": 5}
                                }
                            },
                            {
                                "match_phrase": {
                                    "entities.client": {"query": universal, "boost": 5}
                                }
                            },
                            {
                                "match": {
                                    "filename_edge": {
                                        "query": universal,
                                        "boost": 3,
                                    }
                                }
                            },
                            {
                                "match": {
                                    "texto_edge": {
                                        "query": universal,
                                        "boost": 2,
                                    }
                                }
                            },
                        ]
                    )

            else:
                if exact:
                    # 🔒 Modo exato: só bate em frase/palavra igual
                    should.extend(
                        [
                            {
                                "match_phrase": {
                                    "filename": {
                                        "query": universal,
                                        "boost": 3,
                                    }
                                }
                            },
                            {
                                "match_phrase": {
                                    "texto": {
                                        "query": universal,
                                        "boost": 3,
                                    }
                                }
                            },
                        ]
                    )
                else:
                    # 🔍 Modo normal (Google-like)
                    should.extend(
                        [
                            {"match": {"filename": {"query": universal, "boost": 3}}},
                            {
                                "match": {
                                    "filename_edge": {
                                        "query": universal,
                                        "boost": 3,
                                    }
                                }
                            },
                            {"match": {"texto": {"query": universal, "boost": 1}}},
                            {
                                "match": {
                                    "texto_edge": {
                                        "query": universal,
                                        "boost": 2,
                                    }
                                }
                            },
                            {
                                "match": {
                                    "entities.nif": {"query": universal, "boost": 2}
                                }
                            },
                            {
                                "match": {
                                    "entities.invoice_no": {
                                        "query": universal,
                                        "boost": 2,
                                    }
                                }
                            },
                            {
                                "match": {
                                    "entities.iban": {"query": universal, "boost": 2}
                                }
                            },
                            {
                                "match": {
                                    "entities.supplier": {
                                        "query": universal,
                                        "boost": 2.5,
                                        "fuzziness": "AUTO",
                                    }
                                }
                            },
                            {
                                "match": {
                                    "entities.client": {
                                        "query": universal,
                                        "boost": 2.5,
                                        "fuzziness": "AUTO",
                                    }
                                }
                            },
                        ]
                    )


    elif q or nif or date_from or date_to or min_total or max_total:
        if q:
            must.append(
                {"multi_match": {"query": q, "fields": ["filename^3", "texto"]}}
            )
        if nif:
            must.append({"term": {"entities.nif": nif}})
        if date_from or date_to:
            r = {}
            if date_from:
                r["gte"] = date_from
            if date_to:
                r["lte"] = date_to
            must.append({"range": {"entities.date": r}})
        if (min_total_val is not None) or (max_total_val is not None):
            r = {}
            if min_total_val is not None:
                r["gte"] = min_total_val
            if max_total_val is not None:
                r["lte"] = max_total_val
            must.append({"range": {"entities.total": r}})

    if should:
        query = {"bool": {"must": must, "should": should, "minimum_should_match": 1}}
    else:
        if must:
            query = {"bool": {"must": must}}
        else:
            query = {"match_all": {}}

    body = {
        "query": query,
        "_source": [
            "filename",
            "path",
            "entities",
            "language",
            "indexed_at",
            "texto",
        ],
        "highlight": {
            "fields": {"texto": {"fragment_size": 200, "number_of_fragments": 1}}
        },
        "sort": [
            {"_score": {"order": "desc"}},
            {"indexed_at": {"order": "desc"}},
        ],
    }

    try:
        res = es.search(index=INDEX, size=size, body=body)
        hits = res["hits"]["hits"]
    except Exception as e:
        hits = []
        msg = f"Erro na pesquisa: {str(e)}"

    # Obter lista de pastas disponíveis com base na pasta atual
    available_folders = get_subfolders(current_folder)

    return render_home(
        universal=universal,
        q=q,
        hits=hits,
        nif=nif,
        date_from=date_from,
        date_to=date_to,
        min_total=min_total,
        max_total=max_total,
        msg=msg,
        force_text=force_text,
        current_folder=current_folder,
        available_folders=available_folders,
        exact=exact,
    )


# ------------- API de progresso -------------
@app.get("/api/progress/")
def get_progress_empty():
    """Trata pedidos sem task_id (evita 404 no log)"""
    print("[API] /api/progress/ chamado sem task_id")
    return JSONResponse({
        "status": "not_found",
        "progress": 0,
        "total": 0,
        "current": 0,
        "error": "Task ID is missing"
    })



@app.get("/api/progress/{task_id}")
def get_progress(task_id: str):
    """Retorna o progresso da indexação"""
    print(f"[API] Getting progress for task_id: {task_id}")

    if not task_id:
        print("[API] ERROR: Empty task_id")
        return JSONResponse({
            "status": "error",
            "progress": 0,
            "total": 0,
            "current": 0,
            "error": "Task ID is empty"
        })

    if task_id in indexing_progress:
        raw = indexing_progress[task_id]
        # Criar cópia para não expor objetos não‑serializáveis (ex.: subprocess.Popen)
        data = dict(raw)
        data.pop("process", None)
        print(f"[API] Progress for {task_id}: {data.get('current', 0)}/{data.get('total', 0)}")
        return JSONResponse(data)

    print(f"[API] Task {task_id} not found")
    return JSONResponse({
        "status": "not_found",
        "progress": 0,
        "total": 0,
        "current": 0,
        "error": f"Task {task_id} not found"
    })


def cancel_indexing(task_id: str):
    """Cancela a indexação em execução."""
    print(f"[API] Pedido de cancelamento recebido para {task_id}")

    data = indexing_progress.get(task_id)
    if not data or data.get("status") not in ("starting", "running"):
        return JSONResponse({"status": "error", "message": "Nenhuma tarefa ativa para cancelar."})

    # Sinalizar cancelamento
    data["status"] = "cancelled"
    data["message"] = "❌ Indexação cancelada pelo utilizador."
    indexing_progress[task_id] = data

    # Encerrar processo, se existir
    try:
        proc = data.get("process")
        if proc is not None and proc.poll() is None:
            proc.terminate()
            print(f"[API] Processo de indexação {task_id} terminado.")
    except Exception as e:
        print(f"[API] Erro ao terminar processo {task_id}: {e}")

    return JSONResponse({"status": "cancelled", "message": "Indexação cancelada com sucesso."})


@app.post("/api/cancel/{task_id}")
def api_cancel(task_id: str):
    """Endpoint HTTP para cancelar a indexação atual."""
    return cancel_indexing(task_id)

# ------------- Reindex com progresso -------------
def run_indexing_with_progress(task_id: str, target_dir: str, only_new: bool):
    """Executa indexação e atualiza progresso"""
    print(f"[THREAD] Starting indexing for task {task_id}")
    print(f"[THREAD] Directory: {target_dir}")
    print(f"[THREAD] Only new: {only_new}")
    
    try:
        # Contar ficheiros totais
        total_files = count_local_docs(target_dir)
        print(f"[THREAD] Total files to process: {total_files}")
        
        indexing_progress[task_id] = {
            "status": "running",
            "progress": 0,
            "total": total_files,
            "current": 0,
            "folder": target_dir,
            "process": None,
            "message": ""
        }

        ingest = os.path.join(BASE_DIR, "ingest.py")
        cmd = [sys.executable, ingest, target_dir]
        if only_new:
            cmd.append("new_only")
        
        print(f"[THREAD] Running command: {' '.join(cmd)}")

        # Executar processo
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1
        )

        # Guardar processo para permitir cancelamento
        indexing_progress[task_id]["process"] = process

        # Monitorizar output
        indexed_count = 0
        output_lines = []
        
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            
            if line:
                output_lines.append(line.strip())
                # Contar ficheiros indexados
                if "INDEXED:" in line or "SKIP" in line:
                    indexed_count += 1
                    progress_pct = int((indexed_count / total_files * 100)) if total_files > 0 else 0
                    indexing_progress[task_id].update({
                        "progress": progress_pct,
                        "current": indexed_count,
                        "status": "running"
                    })
                    print(f"[THREAD] Progress: {indexed_count}/{total_files} ({progress_pct}%)")

        # Capturar erros
        stderr_output = process.stderr.read()
        
        # Finalizar
        return_code = process.wait()
        print(f"[THREAD] Process completed with return code: {return_code}")

        current_data = indexing_progress.get(task_id, {})
        if current_data.get("status") == "cancelled":
            final_status = "cancelled"
        else:
            final_status = "completed" if return_code == 0 else "error"

        indexing_progress[task_id].update({
            "status": final_status,
            "progress": 100 if final_status == "completed" else indexing_progress[task_id].get("progress", 0),
            "return_code": return_code,
            "output": "\n".join(output_lines[-30:]),
            "errors": stderr_output[-1000:] if stderr_output else ""
        })

        print(f"[THREAD] Task {task_id} finished")

    except Exception as e:
        print(f"[THREAD] ERROR in task {task_id}: {e}")
        indexing_progress[task_id] = {
            "status": "error",
            "progress": 0,
            "total": 0,
            "current": 0,
            "error": str(e)
        }


@app.api_route("/reindex", methods=["GET", "POST"], response_class=HTMLResponse)
async def reindex(request: Request = None):
    print("\n" + "="*60)
    print("DEBUG: reindex() foi chamado!")
    print("="*60)

    folder = ""
    only_new = False

    # --- Ler parâmetros (POST ou GET) UMA ÚNICA VEZ ---
    if request is not None:
        if request.method == "POST":
            form = await request.form()
            folder = (form.get("folder") or "").strip()
            only_new = (form.get("only_new") or "0") == "1"
        else:
            qp = request.query_params
            folder = (qp.get("folder") or "").strip()
            only_new = (qp.get("only_new") or "0") == "1"

    # Manter caminho exatamente como vem do formulário, só normalizar para absoluto
    target_dir = os.path.abspath(folder or get_default_folder())
    print(f"DEBUG: target_dir = {target_dir!r}")

    if not os.path.isdir(target_dir):
        msg = f"Pasta inválida: {target_dir}"
        print(f"DEBUG: Pasta inválida! Retornando home()")
        return home(msg=msg, folder=target_dir)

    # Criar ID único para esta tarefa
    task_id = str(uuid.uuid4())
    print(f"[REINDEX] Created task_id: {task_id} for folder: {target_dir}")

    # Inicializar progresso imediatamente
    total_files = count_local_docs(target_dir)
    indexing_progress[task_id] = {
        "status": "starting",
        "progress": 0,
        "total": total_files,
        "current": 0,
        "folder": target_dir
    }

    # Iniciar indexação em thread separada
    thread = threading.Thread(
        target=run_indexing_with_progress,
        args=(task_id, target_dir, only_new),
        daemon=True
    )
    thread.start()

    # Retornar página com polling de progresso
    template = env.get_template("progress.html")
    return template.render(
        task_id=task_id,
        folder=target_dir,
        only_new=only_new
    )


# ------------- Função comum para limpar índice -------------
def delete_es_index() -> str:
    try:
        if es.indices.exists(index=INDEX):
            es.indices.delete(index=INDEX)
            return f"🧹 Índice '{INDEX}' apagado com sucesso!"
        else:
            return f"⚠️ O índice '{INDEX}' não existe ou já foi apagado."
    except Exception as e:
        return f"Erro ao apagar índice '{INDEX}': {e}"

def cleanup_orphan_docs() -> tuple[int, int, str]:
    """
    Remove do índice todos os documentos cujo ficheiro em disco já não existe.
    Devolve: (total_no_índice, removidos, erro)
    """
    total_docs = 0
    removed = 0

    try:
        # Usar scan para percorrer todo o índice sem rebentar memória
        for doc in scan(es, index=INDEX, query={"query": {"match_all": {}}}, _source=["path"]):
            total_docs += 1
            src = doc.get("_source", {}) or {}
            path = src.get("path")

            # Se não tiver path ou o ficheiro não existir, marcar para remoção
            if not path or not os.path.exists(path):
                try:
                    es.delete(index=INDEX, id=doc["_id"])
                    removed += 1
                except Exception as e:
                    print(f"[CLEANUP] Erro ao apagar doc {doc['_id']}: {e}")

        return total_docs, removed, ""
    except Exception as e:
        return total_docs, removed, str(e)



# ------------- Limpar índice (da página principal) -------------
@app.post("/delete_index", response_class=HTMLResponse)
async def delete_index(request: Request):
    folder = get_default_folder()
    try:
        form = await request.form()
        raw_folder = (form.get("folder") or "").strip()
        if raw_folder:
            folder = normalize_folder(raw_folder)
    except Exception:
        pass

    msg = delete_es_index()
    return home(msg=msg, folder=folder)

@app.post("/settings/cleanup_index", response_class=HTMLResponse)
async def settings_cleanup_index(request: Request):
    """
    Limpa do índice todos os documentos cujo ficheiro em disco já não existe.
    Acionado pelo botão cinzento nas definições.
    """
    total, removed, error = cleanup_orphan_docs()

    if error:
        msg = f"❌ Erro ao limpar documentos órfãos do índice: {error}"
    else:
        if removed == 0:
            msg = "ℹ️ Não foram encontrados documentos órfãos. O índice já está limpo."
        else:
            msg = f"✅ Limpeza concluída: {removed} documento(s) removido(s) de {total} registados no índice."

    return settings(msg=msg)

# ------------- Upload (caso ainda venhas a usar esta rota) -------------
@app.post("/upload", response_class=HTMLResponse)
async def upload(files: list[UploadFile] = File(...), folder: str = ""):
    target_folder = normalize_folder(folder)
    os.makedirs(target_folder, exist_ok=True)
    
    saved = []
    for f in files:
        base = os.path.basename(f.filename or "documento")
        name, ext = os.path.splitext(base)
        safe = f"{name[:80]}__{uuid.uuid4().hex[:8]}{ext or ''}"
        dest = os.path.join(target_folder, safe)
        with open(dest, "wb") as out:
            out.write(await f.read())
        saved.append(safe)

    # Criar task ID para indexação
    task_id = str(uuid.uuid4())
    
    # Indexar em background
    thread = threading.Thread(
        target=run_indexing_with_progress,
        args=(task_id, target_folder, True),  # only_new=True
        daemon=True
    )
    thread.start()

    msg = f"✅ {len(saved)} ficheiro(s) carregado(s). Indexação em progresso..."
    return home(msg=msg, folder=target_folder)


# ------------- Ver ficheiro -------------
@app.get("/view")
def view_file(p: str):
    if not p:
        return Response("Parametro 'p' em falta.", status_code=400)

    abs_path = os.path.abspath(unquote(p))

    if not os.path.exists(abs_path):
        return Response("Ficheiro não encontrado.", status_code=404)

    media_type, _ = mimetypes.guess_type(abs_path)

    headers = {}
    if media_type and (
        media_type.startswith("image/") or media_type == "application/pdf"
    ):
        headers["Content-Disposition"] = (
            f'inline; filename="{os.path.basename(abs_path)}"'
        )

    return FileResponse(
        abs_path,
        media_type=media_type or "application/octet-stream",
        headers=headers,
        filename=os.path.basename(abs_path),
    )


# ------------- Página de definições -------------
@app.get("/settings", response_class=HTMLResponse)
def settings(msg: str = ""):
    current_default = get_default_folder()
    template = env.get_template("settings.html")
    return template.render(
        msg=msg,
        current_folder=current_default,
        default_folder=current_default,
        local_count=count_local_docs(current_default),
        indexed_count=count_indexed_docs(),  # total no índice
        INDEX=INDEX,
        app_version=APP_VERSION,
    )


@app.post("/settings/set_default_folder", response_class=HTMLResponse)
async def settings_set_default_folder(request: Request):
    global DEFAULT_FOLDER, _config

    form = await request.form()
    raw_folder = (form.get("default_folder") or "").strip()

    if not raw_folder:
        msg = "❌ Por favor indica um caminho de pasta válido."
        return settings(msg=msg)

    new_folder = normalize_folder(raw_folder)

    try:
        os.makedirs(new_folder, exist_ok=True)
    except Exception as e:
        msg = f"❌ Não foi possível criar/verificar a pasta: {e}"
        return settings(msg=msg)

    DEFAULT_FOLDER = new_folder
    _config["default_folder"] = DEFAULT_FOLDER
    save_config(_config)

    msg = f"✅ Pasta por defeito atualizada para: {DEFAULT_FOLDER}"
    return settings(msg=msg)


@app.post("/settings/reset_index", response_class=HTMLResponse)
async def settings_reset_index(request: Request):
    msg = delete_es_index()
    return settings(msg=msg)


if __name__ == "__main__":
    print("DocSearch PT a iniciar...")
    print(f"Pasta de documentos (default): {get_default_folder()}")
    print(f"Elasticsearch: {ES_URL}")
    print(f"Índice: {INDEX}")
    print("Interface: http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
