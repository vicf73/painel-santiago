"""
Camada Bronze (Fase 1 - Lakehouse Local Santiago)
Ingestão fiel das fontes brutas (TXT, CSV, XLSX) para Parquet comprimido (ZSTD)
em lake/bronze/<dominio>/ com controlo incremental por SHA-256 rápido.
"""

import os
import re
import json
import time
import hashlib
from datetime import datetime

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import openpyxl


def _sha256_rapido(caminho: str) -> str:
    h = hashlib.sha256()
    tam = os.path.getsize(caminho)
    h.update(str(tam).encode("utf-8"))
    with open(caminho, "rb") as f:
        h.update(f.read(65536))
        if tam > 131072:
            f.seek(tam - 65536)
            h.update(f.read(65536))
    return h.hexdigest()[:16]


def _norm_cil_series(s: pd.Series) -> pd.Series:
    c = s.fillna("").astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    tam = c.str.len()
    return pd.Series(
        np.where(tam == 5, "600" + c, np.where(tam == 6, "60" + c, c)),
        index=s.index,
        dtype="object",
    )


def _carregar_estado(path_estado: str) -> dict:
    if os.path.exists(path_estado):
        try:
            with open(path_estado, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _salvar_estado(path_estado: str, estado: dict):
    os.makedirs(os.path.dirname(path_estado), exist_ok=True)
    with open(path_estado, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def _precisa_atualizar(estado: dict, chave: str, ficheiros: list[str], out_parquet: str) -> bool:
    if not os.path.exists(out_parquet):
        return True
    assinatura_atual = {os.path.basename(f): _sha256_rapido(f) for f in ficheiros}
    return estado.get(chave) != assinatura_atual


def _registar_estado(estado: dict, chave: str, ficheiros: list[str]):
    estado[chave] = {os.path.basename(f): _sha256_rapido(f) for f in ficheiros}


def _listar_ficheiros(pasta: str, ext: tuple[str, ...] = (".txt",)) -> list[str]:
    if not os.path.isdir(pasta):
        return []
    return sorted([
        os.path.join(pasta, f)
        for f in os.listdir(pasta)
        if not f.startswith("~$")
        and not f.startswith(".")
        and f.lower().endswith(ext)
        and os.path.isfile(os.path.join(pasta, f))
    ])


def _escrever_parquet(df: pd.DataFrame, destino: str):
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, destino, compression="zstd")


# ------------------------------------------------------------------------------
# 1. AUXILIARES (CODIGOS, GEO/PT, IMTT, ITINERARIO, CF1, ANOMALIA)
# ------------------------------------------------------------------------------
def ingerir_bronze_auxiliares(base_santiago: str, base_atual: str, bronze_dir: str, estado: dict) -> dict:
    t0 = time.time()
    pasta_out = os.path.join(bronze_dir, "dim_auxiliares")
    stats = {}

    # CODIGOS.xlsx -> cod_estctr, cod_tpct, cod_uc
    cod_path = os.path.join(base_atual, "CODIGOS.xlsx")
    if os.path.exists(cod_path):
        out_uc = os.path.join(pasta_out, "cod_uc.parquet")
        if _precisa_atualizar(estado, "aux_codigos", [cod_path], out_uc):
            wb = openpyxl.load_workbook(cod_path, data_only=True)
            tabelas = {}
            for s in wb.sheetnames:
                ws = wb[s]
                for tname, ref in ws.tables.items():
                    if tname in ("Tabela9", "Tabela10", "Tabela11"):
                        rows = [[c.value for c in row] for row in ws[ref]]
                        tabelas[tname] = pd.DataFrame(rows[1:], columns=rows[0])
            wb.close()
            _escrever_parquet(tabelas["Tabela9"].astype(str), os.path.join(pasta_out, "cod_estctr.parquet"))
            _escrever_parquet(tabelas["Tabela10"].astype(str), os.path.join(pasta_out, "cod_tpct.parquet"))
            _escrever_parquet(tabelas["Tabela11"].astype(str), out_uc)
            _registar_estado(estado, "aux_codigos", [cod_path])
        stats["codigos"] = "ok"

    # Itinerário
    p_it = os.path.join(base_atual, "itenrar.csv")
    if not os.path.exists(p_it):
        p_it = os.path.join(base_santiago, "itenrar.csv")
    if os.path.exists(p_it):
        out_it = os.path.join(pasta_out, "itinerario.parquet")
        if _precisa_atualizar(estado, "aux_itinerario", [p_it], out_it):
            df_it = pd.read_csv(p_it, sep=";", encoding="latin1", dtype=str)
            _escrever_parquet(df_it, out_it)
            _registar_estado(estado, "aux_itinerario", [p_it])
        stats["itinerario"] = "ok"

    # Excels na pasta santiago (Anomalia, CL_PT, IMTT, cf1_aut)
    from etl_santiago_supabase import localizar_ficheiro_mais_recente
    mapa_xlsx = [
        ("anomalia", ("Anomalia",), "Anomalia de Leitura Setembro 2026.xlsx", 0),
        ("geo_pt", ("CL_PT",), "CL_PT_15_10_26.xlsx", 0),
        ("imtt", ("IMTT",), "IMTT.xlsx", 0),
        ("cf1_autos", ("cf1_aut", "cf1"), "cf1_aut.xlsx", "autos"),
    ]
    for nome_key, prefixos, padrao, sheet in mapa_xlsx:
        try:
            fp = localizar_ficheiro_mais_recente(base_santiago, prefixos, padrao)
            out_pq = os.path.join(pasta_out, f"{nome_key}.parquet")
            if _precisa_atualizar(estado, f"aux_{nome_key}", [fp], out_pq):
                df_x = pd.read_excel(fp, sheet_name=sheet, dtype=str)
                _escrever_parquet(df_x, out_pq)
                _registar_estado(estado, f"aux_{nome_key}", [fp])
            stats[nome_key] = "ok"
        except FileNotFoundError:
            stats[nome_key] = "ausente"

    print(f"  [Bronze 1/7] Auxiliares -> Parquet ({time.time() - t0:.2f}s) {stats}")
    return stats


# ------------------------------------------------------------------------------
# 2. CONTRATO
# ------------------------------------------------------------------------------
def ingerir_bronze_contrato(base_atual: str, bronze_dir: str, estado: dict) -> int:
    t0 = time.time()
    pasta = os.path.join(base_atual, "CONTRATO")
    ficheiros = _listar_ficheiros(pasta, (".txt",))
    out_pq = os.path.join(bronze_dir, "contrato", "contrato.parquet")
    if not _precisa_atualizar(estado, "contrato", ficheiros, out_pq):
        n = pq.read_metadata(out_pq).num_rows
        print(f"  [Bronze 2/7] CONTRATO (cache Parquet): {n:,} linhas ({time.time() - t0:.2f}s)")
        return n

    usecols_26 = [0, 1, 3, 5, 8, 9, 12, 14, 16, 17, 19, 20, 22]
    names_26 = ["EMP_CTR", "UC", "NIB", "CIL", "ID", "TPCT", "NOME", "LOCALIDADE", "PRODUTO", "TARIFA", "ESTCTR", "DT_INI", "DT_BAIXA"]
    usecols_97 = [1, 2, 3, 5, 6, 12, 14, 17, 20, 27, 54]
    names_97 = ["EMP_CTR", "PRODUTO", "UC", "NIB", "CIL", "ESTCTR", "TARIFA", "DT_INI", "DT_BAIXA", "ID", "TPCT"]

    dfs = []
    for f in ficheiros:
        with open(f, "r", encoding="latin1", errors="ignore") as fh:
            n_cols = len(fh.readline().split("\t"))
        if n_cols <= 35:
            df = pd.read_csv(f, sep="\t", header=None, usecols=usecols_26, names=names_26, encoding="utf-8", encoding_errors="replace", quoting=3, dtype=str, on_bad_lines="skip")
        else:
            df = pd.read_csv(f, sep="\t", header=None, usecols=usecols_97, names=names_97, encoding="latin1", quoting=3, dtype=str, on_bad_lines="skip")
            df["NOME"] = None
            df["LOCALIDADE"] = None
            df = df[names_26]
        df["ARQ_ORIGEM"] = os.path.basename(f)
        dfs.append(df)

    df_all = pd.concat(dfs, ignore_index=True)
    df_all["EMP_CTR"] = df_all["EMP_CTR"].fillna("").str.strip().str.lstrip("0")
    for c in ["CIL", "NIB", "ID"]:
        df_all[c] = _norm_cil_series(df_all[c])
    _escrever_parquet(df_all, out_pq)
    _registar_estado(estado, "contrato", ficheiros)
    print(f"  [Bronze 2/7] CONTRATO -> Parquet: {len(df_all):,} linhas ({time.time() - t0:.2f}s)")
    return len(df_all)


# ------------------------------------------------------------------------------
# 3. DIVIDA (GRÃO FATURA PRESERVADO)
# ------------------------------------------------------------------------------
def ingerir_bronze_divida(base_atual: str, bronze_dir: str, estado: dict) -> int:
    t0 = time.time()
    pasta = os.path.join(base_atual, "DIVIDA")
    ficheiros = _listar_ficheiros(pasta, (".txt",))
    out_pq = os.path.join(bronze_dir, "divida", "divida.parquet")
    if not _precisa_atualizar(estado, "divida", ficheiros, out_pq):
        n = pq.read_metadata(out_pq).num_rows
        print(f"  [Bronze 3/7] DIVIDA (cache Parquet): {n:,} faturas ({time.time() - t0:.2f}s)")
        return n

    dfs = []
    for f in ficheiros:
        df = pd.read_csv(
            f, sep="\t", header=None,
            usecols=[0, 4, 5, 9, 10, 11, 12, 13, 15, 19, 26],
            names=["EMP_ID", "UNIDADE", "CIL", "CLI_CONTA", "NOME", "TPCT", "TARIFA", "PRODUTO", "DT_EMISSAO", "NUMFACT", "VAL_DIVIDA"],
            encoding="latin1", quoting=3, dtype=str, on_bad_lines="skip",
        )
        df["ARQ_ORIGEM"] = os.path.basename(f)
        dfs.append(df)

    df_all = pd.concat(dfs, ignore_index=True)
    df_all["EMP_ID"] = df_all["EMP_ID"].fillna("").str.strip().str.lstrip("0")
    df_all["UNIDADE"] = df_all["UNIDADE"].fillna("").str.strip()
    df_all["PRODUTO"] = df_all["PRODUTO"].fillna("").str.strip().str.upper()
    df_all["CIL"] = _norm_cil_series(df_all["CIL"])
    df_all["CLI_CONTA"] = _norm_cil_series(df_all["CLI_CONTA"])
    df_all["VAL_DIVIDA"] = pd.to_numeric(
        df_all["VAL_DIVIDA"].fillna("").str.replace(r"[^0-9,.\-]", "", regex=True), errors="coerce"
    ).fillna(0.0)
    _escrever_parquet(df_all, out_pq)
    _registar_estado(estado, "divida", ficheiros)
    print(f"  [Bronze 3/7] DIVIDA -> Parquet: {len(df_all):,} faturas ({time.time() - t0:.2f}s)")
    return len(df_all)


# ------------------------------------------------------------------------------
# 4. APARELHO
# ------------------------------------------------------------------------------
def ingerir_bronze_aparelho(base_atual: str, bronze_dir: str, estado: dict) -> int:
    t0 = time.time()
    pasta = os.path.join(base_atual, "APARELHO")
    ficheiros = _listar_ficheiros(pasta, (".txt",))
    out_pq = os.path.join(bronze_dir, "aparelho", "aparelho.parquet")
    if not _precisa_atualizar(estado, "aparelho", ficheiros, out_pq):
        n = pq.read_metadata(out_pq).num_rows
        print(f"  [Bronze 4/7] APARELHO (cache Parquet): {n:,} linhas ({time.time() - t0:.2f}s)")
        return n

    dfs = [
        pd.read_csv(f, sep="\t", header=None, usecols=[1, 5, 8, 11, 12, 19, 22, 23],
                    names=["UC", "CIL", "DA_INST", "MODELO", "CONTADOR", "COL20", "DATA_LEIT", "LEITURA"],
                    encoding="cp1252", quoting=3, dtype=str, on_bad_lines="skip")
        for f in ficheiros
    ]
    df_all = pd.concat(dfs, ignore_index=True)
    df_all["CIL"] = _norm_cil_series(df_all["CIL"])
    _escrever_parquet(df_all, out_pq)
    _registar_estado(estado, "aparelho", ficheiros)
    print(f"  [Bronze 4/7] APARELHO -> Parquet: {len(df_all):,} linhas ({time.time() - t0:.2f}s)")
    return len(df_all)


# ------------------------------------------------------------------------------
# 5. FATURACAO (CONCEITO) - PARTICIONADO POR FICHEIRO/LOTE
# ------------------------------------------------------------------------------
def ingerir_bronze_faturacao(base_atual: str, bronze_dir: str, estado: dict, ucs_sul: set[str]) -> int:
    t0 = time.time()
    pasta = os.path.join(base_atual, "FATURAÇAO")
    ficheiros = _listar_ficheiros(pasta, (".txt",))
    pasta_out = os.path.join(bronze_dir, "faturacao_conceito")
    os.makedirs(pasta_out, exist_ok=True)

    tot_linhas = 0
    novos = 0
    for fp in ficheiros:
        nome = os.path.basename(fp)
        out_pq = os.path.join(pasta_out, nome.replace(".txt", ".parquet"))
        if not _precisa_atualizar(estado, f"fat_{nome}", [fp], out_pq):
            tot_linhas += pq.read_metadata(out_pq).num_rows
            continue

        novos += 1
        m_ym = re.search(r"\.(\d{6})\d{2}\.txt$", nome)
        ym = m_ym.group(1) if m_ym else "000000"

        rows = []
        last_prefix = None
        last_in_sul = False
        with open(fp, "rb") as fh:
            for raw in fh:
                try:
                    line = raw.decode("utf-8")
                except UnicodeDecodeError:
                    line = raw.decode("latin1", errors="replace")
                parts = line.rstrip("\r\n").split("\t")
                n_p = len(parts)
                if n_p >= 23:
                    uc_s = parts[1].strip().zfill(9)
                    last_in_sul = uc_s in ucs_sul
                    if not last_in_sul:
                        last_prefix = None
                        continue
                    last_prefix = parts[:20]
                    conc, qtd_s, val_q_s = parts[20].strip(), parts[21].strip(), parts[22].strip()
                elif n_p >= 3 and last_prefix is not None and last_in_sul:
                    parts = last_prefix + parts[:3]
                    conc, qtd_s, val_q_s = parts[20].strip(), parts[21].strip(), parts[22].strip()
                else:
                    continue

                rows.append((
                    parts[0].strip().lstrip("0"),  # EMP
                    parts[1].strip().zfill(9),     # UC
                    parts[2].strip().upper(),      # PRODUTO
                    parts[4].strip(),              # CIL
                    parts[7].strip(),              # ID_CLIENTE
                    parts[11].strip(),             # TARIFA
                    parts[12].strip(),             # DT_ESTADO
                    parts[13].strip(),             # DT_FATURA
                    parts[15].strip(),             # NUMFACT
                    parts[18].strip(),             # VAL_TOT
                    conc, qtd_s, val_q_s, ym,
                ))

        df_f = pd.DataFrame(rows, columns=[
            "EMP", "UC", "PRODUTO", "CIL", "ID_CLIENTE", "TARIFA",
            "DT_ESTADO", "DT_FATURA", "NUMFACT", "VAL_TOT", "CONCEITO", "QTD_CONSUMO", "VAL_CONCEITO", "LOTE_YM",
        ])
        df_f["CIL"] = _norm_cil_series(df_f["CIL"])
        df_f["VAL_TOT"] = pd.to_numeric(df_f["VAL_TOT"], errors="coerce").fillna(0.0)
        df_f["QTD_CONSUMO"] = pd.to_numeric(df_f["QTD_CONSUMO"], errors="coerce").fillna(0.0)
        df_f["VAL_CONCEITO"] = pd.to_numeric(df_f["VAL_CONCEITO"], errors="coerce").fillna(0.0)
        _escrever_parquet(df_f, out_pq)
        _registar_estado(estado, f"fat_{nome}", [fp])
        tot_linhas += len(df_f)

    print(f"  [Bronze 5/7] FATURAÇAO (Sul) -> Parquet: {tot_linhas:,} linhas ({novos} novos/atualizados, {time.time() - t0:.2f}s)")
    return tot_linhas


# ------------------------------------------------------------------------------
# 6. COBRANCA (MULTI-EMPRESA 17/21/07/70)
# ------------------------------------------------------------------------------
def ingerir_bronze_cobranca(base_atual: str, bronze_dir: str, estado: dict) -> int:
    t0 = time.time()
    pasta = os.path.join(base_atual, "cob_26")
    ficheiros = _listar_ficheiros(pasta, (".txt",))
    pasta_out = os.path.join(bronze_dir, "cobranca")
    os.makedirs(pasta_out, exist_ok=True)

    tot_linhas = 0
    novos = 0
    for fp in ficheiros:
        if os.path.getsize(fp) == 0:
            continue
        nome = os.path.basename(fp)
        out_pq = os.path.join(pasta_out, nome.replace(".txt", ".parquet"))
        if not _precisa_atualizar(estado, f"cob_{nome}", [fp], out_pq):
            tot_linhas += pq.read_metadata(out_pq).num_rows
            continue

        novos += 1
        nome_up = nome.upper()
        if "E021" in nome_up:
            emp_fp = "21"
        elif "SARL" in nome_up or "E070" in nome_up:
            emp_fp = "70"
        elif "SUL" in nome_up or "E007" in nome_up:
            emp_fp = "7"
        else:
            emp_fp = "17"

        df = pd.read_csv(
            fp, sep="\t", header=None, usecols=[0, 1, 8, 11, 16, 21],
            names=["UC", "CIL", "DATA_COBR", "VALOR", "TIPO_DOC", "DATA_FAT"],
            dtype=str, quoting=3, encoding="latin1", on_bad_lines="skip",
        )
        if len(df) == 0:
            continue
        df["EMP"] = emp_fp
        uc = df["UC"].fillna("").str.strip()
        df["UC"] = np.where(uc == "", "00", uc.str.zfill(9))
        df["CIL"] = _norm_cil_series(df["CIL"])
        df["TIPO_DOC"] = df["TIPO_DOC"].fillna("").str.strip().str.upper()
        df["VALOR"] = pd.to_numeric(
            df["VALOR"].fillna("").str.replace(r"[^0-9,.\-]", "", regex=True), errors="coerce"
        ).fillna(0.0)
        df["ARQ_ORIGEM"] = nome
        _escrever_parquet(df, out_pq)
        _registar_estado(estado, f"cob_{nome}", [fp])
        tot_linhas += len(df)

    print(f"  [Bronze 6/7] COBRANCA -> Parquet: {tot_linhas:,} linhas ({novos} novos/atualizados, {time.time() - t0:.2f}s)")
    return tot_linhas


# ------------------------------------------------------------------------------
# 7. INSPECOES CEA (cea_24, cea_25, cea_26, CEA_AP) + ORDENS DE SERVICO (or_serv)
# ------------------------------------------------------------------------------
def ingerir_bronze_cea_e_os(base_atual: str, bronze_dir: str, estado: dict) -> tuple[int, int]:
    t0 = time.time()
    # CEA
    arqs_cea = []
    for sub in ["cea_24", "cea_25", "cea_26", "CEA_AP"]:
        for fp in _listar_ficheiros(os.path.join(base_atual, sub), (".csv",)):
            arqs_cea.append((sub, fp))
    out_cea = os.path.join(bronze_dir, "inspecao_cea", "inspecao_cea.parquet")
    fps_cea = [x[1] for x in arqs_cea]
    if fps_cea and _precisa_atualizar(estado, "cea", fps_cea, out_cea):
        dfs_c = []
        for sub, fp in arqs_cea:
            try:
                df_c = pd.read_csv(fp, sep=";", encoding="utf-8", dtype=str, on_bad_lines="skip")
            except UnicodeDecodeError:
                df_c = pd.read_csv(fp, sep=";", encoding="latin1", dtype=str, on_bad_lines="skip")
            df_c["PASTA_ORIGEM"] = sub
            df_c["ARQ_ORIGEM"] = os.path.basename(fp)
            dfs_c.append(df_c)
        df_cea_all = pd.concat(dfs_c, ignore_index=True)
        if "CIL" in df_cea_all.columns:
            df_cea_all["CIL"] = _norm_cil_series(df_cea_all["CIL"])
        _escrever_parquet(df_cea_all, out_cea)
        _registar_estado(estado, "cea", fps_cea)
        n_cea = len(df_cea_all)
    elif os.path.exists(out_cea):
        n_cea = pq.read_metadata(out_cea).num_rows
    else:
        n_cea = 0

    # Ordens de Serviço (or_serv)
    fps_os = _listar_ficheiros(os.path.join(base_atual, "or_serv"), (".txt",))
    out_os = os.path.join(bronze_dir, "ordem_servico", "ordem_servico.parquet")
    if fps_os and _precisa_atualizar(estado, "os", fps_os, out_os):
        dfs_o = []
        for fp in fps_os:
            df_o = pd.read_csv(
                fp, sep="\t", header=None, usecols=[0, 1, 3, 4, 5, 7, 9, 11, 12, 15, 16, 17, 18, 19],
                names=["EMP", "UC", "TIPO_OS", "PRODUTO", "CIL", "NUM_OS", "DESC_OS", "EST_OS", "DT_EXEC", "DT_EMISSAO", "DT_SOLIC", "ID_CLIENTE", "NOME", "LOCALIDADE"],
                encoding="utf-8", encoding_errors="replace", quoting=3, dtype=str, on_bad_lines="skip",
            )
            df_o["ARQ_ORIGEM"] = os.path.basename(fp)
            dfs_o.append(df_o)
        df_os_all = pd.concat(dfs_o, ignore_index=True)
        df_os_all["CIL"] = _norm_cil_series(df_os_all["CIL"])
        _escrever_parquet(df_os_all, out_os)
        _registar_estado(estado, "os", fps_os)
        n_os = len(df_os_all)
    elif os.path.exists(out_os):
        n_os = pq.read_metadata(out_os).num_rows
    else:
        n_os = 0

    print(f"  [Bronze 7/7] CEA ({n_cea:,} insp.) + OS ({n_os:,} ordens) -> Parquet ({time.time() - t0:.2f}s)")
    return n_cea, n_os


def executar_bronze(base_santiago: str, base_atual: str) -> dict:
    t_ini = time.time()
    bronze_dir = os.path.join(base_santiago, "lake", "bronze")
    path_estado = os.path.join(bronze_dir, "_estado_bronze.json")
    estado = _carregar_estado(path_estado)

    print("=" * 72)
    print(" FASE 1 - CAMADA BRONZE (PARQUET ZSTD INCREMENTAL)")
    print("=" * 72)

    ingerir_bronze_auxiliares(base_santiago, base_atual, bronze_dir, estado)

    # Obter lista de UCs Sul de cod_uc.parquet
    df_uc = pd.read_parquet(os.path.join(bronze_dir, "dim_auxiliares", "cod_uc.parquet"))
    ucs_sul = {
        str(int(float(c))).zfill(9)
        for c, ilha in zip(df_uc["COD_UNI"], df_uc["ILHA"])
        if str(c).strip() not in ("", "None", "nan") and str(ilha).strip() in {"Santiago", "Fogo", "Maio", "Brava"}
    }

    n_ctr = ingerir_bronze_contrato(base_atual, bronze_dir, estado)
    n_div = ingerir_bronze_divida(base_atual, bronze_dir, estado)
    n_apa = ingerir_bronze_aparelho(base_atual, bronze_dir, estado)
    n_fat = ingerir_bronze_faturacao(base_atual, bronze_dir, estado, ucs_sul)
    n_cob = ingerir_bronze_cobranca(base_atual, bronze_dir, estado)
    n_cea, n_os = ingerir_bronze_cea_e_os(base_atual, bronze_dir, estado)

    _salvar_estado(path_estado, estado)
    resumo = {
        "executado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "duracao_s": round(time.time() - t_ini, 2),
        "contrato": n_ctr,
        "divida": n_div,
        "aparelho": n_apa,
        "faturacao_conceito": n_fat,
        "cobranca": n_cob,
        "inspecao_cea": n_cea,
        "ordem_servico": n_os,
    }
    print(f" BRONZE CONCLUÍDA em {resumo['duracao_s']:.2f}s -> {bronze_dir}")
    return resumo
