import re
from datetime import datetime

# Regex básicos (PT)
NIF_RE = re.compile(r"\b(PT)?\s?(\d{9})\b")
DATE_RE = re.compile(r"\b(\d{2}[/-]\d{2}[/-]\d{4}|\d{4}-\d{2}-\d{2})\b")
INV_RE = re.compile(r"\b(?:FATURA|FAT|FT|FA|FACTURA|INV|F\.?\s?T\.?)[\s:]*([A-Z0-9_\-/.]+)\b", re.IGNORECASE)
SUPPLIER_RE = re.compile(r"\b(?:Fornecedor|Emitente|Vendedor|Empresa)[:\s]+(.{3,60})", re.IGNORECASE)
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}(?:[A-Z0-9]?){0,16}\b")
VAT_RE = re.compile(r"\b(?:IVA|VAT)[^0-9]{0,10}([0-9]+(?:[.,][0-9]{2})?)\b", re.IGNORECASE)
TOTAL_RE = re.compile(r"\b(?:TOTAL(?:\s+GERAL)?|TOTAL\s*A\s*PAGAR|VALOR\s*A\s*PAGAR|MONTANTE\s*FINAL)[:\s]*([0-9]+(?:[\.,][0-9]{2})?)\b", re.IGNORECASE)

def _valid_nif(nif: str) -> bool:
    # Validação módulo 11 (heurística simples)
    if not (nif and len(nif) == 9 and nif.isdigit() and nif[0] in "125689"):
        return False
    total = sum(int(nif[i]) * (9 - i) for i in range(8))
    check = 11 - (total % 11)
    if check >= 10:
        check = 0
    return check == int(nif[8])

def _parse_date(s: str):
    s2 = s.replace('/', '-')
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s2, fmt).date().isoformat()
        except Exception:
            pass
    return None

def _to_float(s: str):
    if s is None:
        return None
    s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except Exception:
        return None

def parse_invoice_fields(text: str):
    out = {"nif": None, "supplier": None, "invoice_no": None, "iban": None,
           "vat": None, "total": None, "date": None}

    m = NIF_RE.search(text)
    if m:
        p = m.group(2)
        if _valid_nif(p):
            out["nif"] = p

    d = DATE_RE.search(text)
    if d:
        out["date"] = _parse_date(d.group(1))

    inv = INV_RE.search(text)
    if inv:
        out["invoice_no"] = inv.group(1)

    sup = SUPPLIER_RE.search(text)
    if sup:
        out["supplier"] = sup.group(1).strip()

    iban = IBAN_RE.search(text)
    if iban:
        out["iban"] = iban.group(0)

    vat = VAT_RE.search(text)
    if vat:
        out["vat"] = _to_float(vat.group(1))

    tot = TOTAL_RE.search(text)
    if tot:
        out["total"] = _to_float(tot.group(1))

    return out
