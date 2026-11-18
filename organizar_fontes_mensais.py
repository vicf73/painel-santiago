"""
Organizador Automático de Fontes Mensais — Região Sul (DPO / Santiago).

Varre a pasta de downloads/extrações (PASTA_SCRIP, por defeito Desktop\\scrip),
filtra exclusivamente ficheiros da Região Sul (017, 021, 007, 070/SARL),
descompacta .txt.gz quando necessário e encaminha para as pastas oficiais em
Atual_script (cob_26, FATURAÇAO, or_serv, CONTRATO, DIVIDA, APARELHO) sem
duplicar ficheiros nem misturar snapshots antigos.
"""

import argparse
import gzip
import os
import re
import shutil
import time
from collections import defaultdict

BASE_SCRIP = os.environ.get("PASTA_SCRIP", r"C:\Users\VICTOR FERREIRA\Desktop\scrip")
BASE_ATUAL = os.environ.get("PASTA_ATUAL_SCRIPT", r"C:\Users\VICTOR FERREIRA\Desktop\Atual_script")

# Padrões de exclusão (Norte / Mindelo) e inclusão (Região Sul)
EXCLUIR_RE = re.compile(r"(NORTE|MINDELO|005\s*-\s*NORTE)", re.IGNORECASE)
SUL_RE = re.compile(r"(E017|E021|E007|E070|SARL|PRAIA|SUL|017|021|007|070)", re.IGNORECASE)
DATA_LOTE_RE = re.compile(r"\.(20\d{6})\.")


def _extrair_data_lote(nome: str) -> str:
    m = DATA_LOTE_RE.search(nome)
    return m.group(1) if m else ""


COB_PREFIXES = (
    "3COB_TCXRECCONC_E021.",
    "3COB_TCXRECCONC_OUTROS_E017.",
    "3COB_TCXRECCONC_OUTROS_SUL_EN.",
    "3COB_TCXRECCONC_PRAIA_E017.",
    "3COB_TCXRECCONC_PRAIA_SUL_EN.",
    "3COB_TCXRECCONC_SARL_AG.",
    "3COB_TCXRECCONC_SARL_EN.",
    "E007_COB_TCXRECCONC.",
    "E017_COB_TCXRECCONC.",
    "E021_COB_TCXRECCONC.",
    "E070_COB_TCXRECCONC.",
)


def _classificar_ficheiro(nome_txt: str) -> tuple[str, bool] | None:
    """Devolve (subpasta_destino, eh_snapshot) ou None se não for fonte suportada."""
    nu = nome_txt.upper()
    if not nu.endswith(".TXT"):
        return None
    data_arq = _extrair_data_lote(nome_txt)
    # Lotes a partir de 20260201 (referentes a Jan/2026 em diante; 20260101 é Dez/2025)
    if not data_arq or data_arq < "20260201":
        return None

    if nu.startswith(COB_PREFIXES):
        return ("cob_26", False)
    if nu.startswith(("Z3FACTURAS_CONCEITO_TRECIBOS_E017.", "Z3FACTURAS_CONCEITO_TRECIBOS_E021.")):
        return ("FATURAÇAO", False)
    if nu.startswith("OS_E017."):
        return ("or_serv", False)
    if nu.startswith(("2CONTRATOS_E017.", "TCONTRATOS_E021.", "TCONTRATOS_SUL_")):
        return ("CONTRATO", True)
    if nu.startswith(("0DIVIDAS_", "1DIVIDAS_")):
        return ("DIVIDA", True)
    if nu.startswith("3APARELHOS_E017."):
        return ("APARELHO", True)
    return None


def _max_data_destino(pasta_dst: str) -> str:
    if not os.path.isdir(pasta_dst):
        return ""
    datas = [_extrair_data_lote(fn) for fn in os.listdir(pasta_dst)]
    datas = [d for d in datas if d]
    return max(datas) if datas else ""


def organizar_fontes(dry_run: bool = False) -> dict:
    t0 = time.time()
    print("=" * 72)
    print(" ORGANIZADOR AUTOMÁTICO DE FONTES MENSAIS (SCRIP -> ATUAL_SCRIPT)")
    print("=" * 72)
    if not os.path.isdir(BASE_SCRIP):
        print(f"   [AVISO] Pasta de origem não encontrada: {BASE_SCRIP}")
        return {"copiados": 0, "ignorados": 0}

    max_datas = {
        sub: _max_data_destino(os.path.join(BASE_ATUAL, sub))
        for sub in ("CONTRATO", "DIVIDA", "APARELHO")
    }

    copiados_por_pasta = defaultdict(int)
    ja_atualizados = 0
    ignorados_antigos = 0
    vistos = set()

    for root, _, files in os.walk(BASE_SCRIP):
        if EXCLUIR_RE.search(root):
            continue
        for fn in files:
            low = fn.lower()
            if not (low.endswith(".txt") or low.endswith(".txt.gz")):
                continue
            if EXCLUIR_RE.search(fn):
                continue

            fp_src = os.path.join(root, fn)
            if not os.path.isfile(fp_src):
                continue

            nome_txt = fn[:-3] if low.endswith(".gz") else fn
            if not (SUL_RE.search(nome_txt) or SUL_RE.search(root)):
                continue

            classe = _classificar_ficheiro(nome_txt)
            if not classe:
                continue

            subpasta, eh_snapshot = classe
            chave_v = (subpasta, nome_txt.lower())
            if chave_v in vistos:
                continue
            vistos.add(chave_v)
            data_arq = _extrair_data_lote(nome_txt)

            # Snapshots: nunca copiar lotes mais antigos que o snapshot atual em Atual_script
            if eh_snapshot and max_datas.get(subpasta) and data_arq and data_arq < max_datas[subpasta]:
                ignorados_antigos += 1
                continue

            pasta_dst = os.path.join(BASE_ATUAL, subpasta)
            os.makedirs(pasta_dst, exist_ok=True)
            fp_dst = os.path.join(pasta_dst, nome_txt)

            precisa_copiar = False
            if not os.path.exists(fp_dst):
                precisa_copiar = True
            elif not low.endswith(".gz"):
                # Se já existe, só atualizar se o ficheiro de origem for mais recente E tiver mais linhas/bytes
                if os.path.getmtime(fp_src) > os.path.getmtime(fp_dst) + 5 and os.path.getsize(fp_src) != os.path.getsize(fp_dst):
                    precisa_copiar = True

            if not precisa_copiar:
                ja_atualizados += 1
                continue

            if dry_run:
                print(f"   [SIMULAÇÃO] {fp_src} -> {subpasta}\\{nome_txt}")
            else:
                if low.endswith(".gz"):
                    with gzip.open(fp_src, "rb") as fg_in, open(fp_dst, "wb") as f_out:
                        shutil.copyfileobj(fg_in, f_out)
                else:
                    shutil.copy2(fp_src, fp_dst)
                print(f"   [COPIADO] {subpasta}\\{nome_txt}")
            copiados_por_pasta[subpasta] += 1

    tot_cop = sum(copiados_por_pasta.values())
    print(f"   Resumo: {tot_cop} novo(s)/atualizado(s) | {ja_atualizados} já existentes | {ignorados_antigos} snapshots antigos ignorados ({time.time() - t0:.2f}s)")
    for k, v in sorted(copiados_por_pasta.items()):
        print(f"     - {k}: +{v} ficheiro(s)")
    return {"copiados": tot_cop, "ja_atualizados": ja_atualizados, "ignorados_antigos": ignorados_antigos}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Organizador automático de fontes mensais (scrip -> Atual_script)")
    parser.add_argument("--dry-run", action="store_true", help="Apenas simular sem copiar ficheiros")
    args = parser.parse_args()
    organizar_fontes(dry_run=args.dry_run)
