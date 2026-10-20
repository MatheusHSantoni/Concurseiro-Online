"""Extração experimental. Layouts de PDFs variam: revisar TODO candidato."""
import re
import pymupdf

# Exemplo: "QUESTÃO 9" ou "Questão 9"; pode falhar em provas com duas colunas.
QUESTION = re.compile(r'(?im)^\s*(?:QUESTÃO|Questão|ITEM|Item)\s+(\d{1,3})\s*[-–.:]?\s*$')


def extract_candidates(pdf_bytes):
    with pymupdf.open(stream=pdf_bytes, filetype='pdf') as doc:
        text = '\n'.join(page.get_text(sort=True) for page in doc)
    matches = list(QUESTION.finditer(text))
    result = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        statement = text[match.end():end].strip()
        if 20 <= len(statement) <= 6000:
            result.append({'number': int(match.group(1)), 'statement': statement})
    return result
