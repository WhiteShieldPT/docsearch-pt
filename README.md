
DocSearch PT – Upgrade de OCR/AI

Este upgrade privilegia qualidade máxima de reconhecimento de faturas:
- Mantém Tika para texto nativo.
- OCR híbrido: Tesseract (afinando OEM/PSM/DPI) + EasyOCR (fallback).
- Extração de entidades com IA (spaCy NER) para preencher lacunas.

1) Pré‑requisitos
- Tesseract instalado (Windows: C:\Program Files\Tesseract-OCR\tesseract.exe).
- (Opcional) Apache Tika em http://localhost:9998/tika.

2) Instalar dependências
    pip install -r requirements-ocr-ai.txt
    python -m spacy download pt_core_news_md

   Se torch der erro, siga instruções em https://pytorch.org/get-started/locally/

3) Substituir o ficheiro
- Copie este ingest.py para a raiz do projeto (onde está o atual).

4) Executar
    python ingest.py <pasta_com_documentos>
ou use o botão "Atualizar Documentos" na UI.

Dicas
- Tesseract: --oem 3 --psm 6 --dpi 300
- PDF render scale=2.5 (equilíbrio).

Bom trabalho! 🚀
