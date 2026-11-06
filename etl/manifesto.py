"""
Módulo 1.1 - Manifesto e Validação Pré-Carga de Ficheiros Fonte (Projeto Santiago)
Gera manifesto_fontes.json com inventário auditável (caminho, tamanho, data de modificação e hash SHA-256)
de todos os ficheiros TXT e Excel antes de iniciar o ETL.
"""

import os
import json
import hashlib
from datetime import datetime


def _hash_ficheiro_rapido(caminho: str) -> str:
    """Calcula SHA-256 rápido (primeiros e últimos 64KB + tamanho) para auditoria de fontes."""
    h = hashlib.sha256()
    tam = os.path.getsize(caminho)
    h.update(str(tam).encode("utf-8"))
    with open(caminho, "rb") as f:
        bloco_ini = f.read(65536)
        h.update(bloco_ini)
        if tam > 131072:
            f.seek(tam - 65536)
            h.update(f.read(65536))
    return h.hexdigest()[:16]


def _info_ficheiro(caminho: str, categoria: str) -> dict:
    st = os.stat(caminho)
    return {
        "categoria": categoria,
        "ficheiro": os.path.basename(caminho),
        "caminho": caminho,
        "tamanho_bytes": int(st.st_size),
        "tamanho_mb": round(st.st_size / (1024 * 1024), 2),
        "modificado_em": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "sha256_curto": _hash_ficheiro_rapido(caminho),
    }


def gerar_e_validar_manifesto(base_santiago: str, base_atual_script: str) -> dict:
    """
    Inspeciona todas as fontes do ETL, valida a existência e integridade mínima
    e grava manifesto_fontes.json na raiz e em backups/.
    """
    fontes = []
    erros = []

    # 1. Pastas TXT do sistema comercial (CONTRATO, DIVIDA, APARELHO, cob_26)
    for pasta_nome in ["CONTRATO", "DIVIDA", "APARELHO", "cob_26"]:
        pasta_dir = os.path.join(base_atual_script, pasta_nome)
        if not os.path.isdir(pasta_dir):
            if pasta_nome != "cob_26":
                erros.append(f"Pasta obrigatória ausente: {pasta_dir}")
            continue
        arqs = sorted([
            os.path.join(pasta_dir, f)
            for f in os.listdir(pasta_dir)
            if not f.startswith("~$") and not f.startswith(".") and os.path.isfile(os.path.join(pasta_dir, f))
        ])
        if not arqs and pasta_nome != "cob_26":
            erros.append(f"Pasta obrigatória vazia: {pasta_dir}")
        for arq in arqs:
            info = _info_ficheiro(arq, pasta_nome)
            if info["tamanho_bytes"] == 0:
                erros.append(f"Ficheiro vazio (0 bytes): {arq}")
            fontes.append(info)

    # 2. Ficheiros Excel na pasta santiago
    excels_obrigatorios = [
        ("CODIGOS", "CODIGOS.xlsx"),
        ("ANOMALIA", "Anomalia de Leitura Setembro 2026.xlsx"),
        ("FATURACAO_T3", "Fat_piv.xlsx"),
        ("GEOREF_PT", "CL_PT_15_10_26.xlsx"),
        ("IMTT", "IMTT.xlsx"),
        ("CF1_AUTOS", "cf1_aut.xlsx"),
        ("COBRANCA_2026", "COB_J.xlsx"),
    ]
    for cat, nome_xlsx in excels_obrigatorios:
        caminho = os.path.join(base_santiago, nome_xlsx)
        if os.path.isfile(caminho):
            info = _info_ficheiro(caminho, cat)
            if info["tamanho_bytes"] == 0:
                erros.append(f"Excel vazio (0 bytes): {caminho}")
            fontes.append(info)
        elif cat not in ("CF1_AUTOS", "COBRANCA_2026"):
            erros.append(f"Ficheiro Excel obrigatório não encontrado: {caminho}")

    manifesto = {
        "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "base_santiago": base_santiago,
        "base_atual_script": base_atual_script,
        "total_ficheiros": len(fontes),
        "tamanho_total_mb": round(sum(f["tamanho_bytes"] for f in fontes) / (1024 * 1024), 2),
        "validacao_ok": len(erros) == 0,
        "erros": erros,
        "fontes": fontes,
    }

    caminho_manifesto = os.path.join(base_santiago, "manifesto_fontes.json")
    with open(caminho_manifesto, "w", encoding="utf-8") as f:
        json.dump(manifesto, f, ensure_ascii=False, indent=2)

    pasta_bkp = os.path.join(base_santiago, "backups")
    os.makedirs(pasta_bkp, exist_ok=True)
    tag_mes = datetime.now().strftime("%Y%m")
    caminho_bkp = os.path.join(pasta_bkp, f"manifesto_{tag_mes}.json")
    with open(caminho_bkp, "w", encoding="utf-8") as f:
        json.dump(manifesto, f, ensure_ascii=False, indent=2)

    print(
        f"  [0/9] Manifesto de Fontes validado: {manifesto['total_ficheiros']} ficheiros "
        f"({manifesto['tamanho_total_mb']:.2f} MB) -> {caminho_manifesto}"
    )
    if erros:
        raise RuntimeError("Falha na validação do Manifesto de Fontes:\n  - " + "\n  - ".join(erros))

    return manifesto
