import requests, json

ES = "http://localhost:9200"
INDEX = "files"

mapping = {
  "mappings": {
    "properties": {
      "filename": { "type": "keyword" },
      "path": { "type": "keyword" },
      "size": { "type": "long" },
      "created_at": { "type": "date", "format": "epoch_second" },
      "metadata": { "type": "object", "enabled": True },
      "language": { "type": "keyword" },
      "ocr_used": { "type": "boolean" },
      "ocr_engine": { "type": "keyword" },
      "text": { "type": "text", "analyzer": "standard" },
      "entities": {
        "properties": {
          "nif":        {"type": "keyword"},
          "supplier":   {"type": "keyword"},
          "invoice_no": {"type": "keyword"},
          "iban":       {"type": "keyword"},
          "vat":        {"type": "scaled_float", "scaling_factor": 100},
          "total":      {"type": "scaled_float", "scaling_factor": 100},
          "date":       {"type": "date", "format": "yyyy-MM-dd"}
        }
      },
      "embedding": {
        "type": "dense_vector",
        "dims": 384,
        "index": True,
        "similarity": "cosine"
      }
    }
  }
}

def put_index():
    r = requests.put(f"{ES}/{INDEX}", headers={"Content-Type":"application/json"}, data=json.dumps(mapping))
    print("Status:", r.status_code, r.text[:200])

if __name__ == "__main__":
    try:
        requests.delete(f"{ES}/{INDEX}")
        print("Índice antigo removido.")
    except Exception:
        pass
    put_index()
