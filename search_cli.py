from elasticsearch import Elasticsearch
import sys

ES_URL = "http://localhost:9200"
INDEX = "files"

def search(es, q, size=10):
    body = {
        "query": {
            "multi_match": {
                "query": q,
                "fields": ["filename^3", "text"]
            }
        },
        "_source": ["filename", "path", "entities", "language"]
    }
    res = es.search(index=INDEX, size=size, body=body)
    return res["hits"]["hits"]

def main():
    if len(sys.argv) < 2:
        print("Uso: python search_cli.py "termo de pesquisa"")
        sys.exit(1)
    q = sys.argv[1]
    es = Elasticsearch(ES_URL)
    hits = search(es, q)
    for h in hits:
        src = h["_source"]
        print(f"{h['_score']:.2f} | {src.get('filename')} | {src.get('path')} | ENT:{src.get('entities')} | LANG:{src.get('language')}")

if __name__ == "__main__":
    main()
