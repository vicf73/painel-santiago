"""
Pipeline ETL Profissional - Projeto Santiago (EDEC)
Migração 1:1 da lógica do Power Query (M) para Python de alta performance
com integração de Autos de Fraude (cf1_aut.xlsx) e Cobrança 2026 (COB_J.xlsx)
e sincronização em lote (Upsert Paralelo) para o Supabase (edec-app).

Autor: Victor Ferreira / EDEC
"""

import os
import sys
import time
import math
import json
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import openpyxl
import requests

sys.stdout.reconfigure(encoding="utf-8")

# ==============================================================================
# 0. CONFIGURAÇÕES E CAMINHOS
# ==============================================================================
BASE_SANTIAGO = os.path.dirname(os.path.abspath(__file__))
BASE_ATUAL_SCRIPT = r"C:\Users\VICTOR FERREIRA\Desktop\Atual_script"

# Carregar variáveis do .env se existir
ENV_PATH = os.path.join(BASE_SANTIAGO, ".env")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://esbbohmkgbcrpegqvagk.supabase.co")
# Segurança (Fase 0): a chave anon (pública) é APENAS de leitura.
# A escrita no Supabase exige a chave secreta service_role, guardada SOMENTE no .env local
# (nunca no HTML nem no GitHub). Obter em: Supabase > Project Settings > API Keys.
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
BASE_ATUAL_SCRIPT = os.environ.get("PASTA_ATUAL_SCRIPT", BASE_ATUAL_SCRIPT)
BASE_SANTIAGO = os.environ.get("PASTA_SANTIAGO", BASE_SANTIAGO)


# ==============================================================================
# 1. CARGA E FILTRAGEM DE FICHEIROS (CONTRATO)
# ==============================================================================
def carregar_contratos() -> pd.DataFrame:
    t0 = time.time()
    pasta_contrato = os.path.join(BASE_ATUAL_SCRIPT, "CONTRATO")
    ficheiros = sorted([
        os.path.join(pasta_contrato, f)
        for f in os.listdir(pasta_contrato)
        if not f.startswith("~$")
        and not f.startswith(".")
        and os.path.isfile(os.path.join(pasta_contrato, f))
    ])
    if not ficheiros:
        raise FileNotFoundError(f"Nenhum ficheiro encontrado em {pasta_contrato}")

    # Colunas Power Query (1-based) -> Python (0-based):
    # Column2(1)->UC, Column4(3)->NIB, Column6(5)->CIL, Column9(8)->ID,
    # Column10(9)->TPCT, Column13(12)->NOME, Column15(14)->LOCALIDADE,
    # Column17(16)->PRODUTO, Column18(17)->TARIFA, Column20(19)->ESTCTR
    usecols = [1, 3, 5, 8, 9, 12, 14, 16, 17, 19]
    names = ["UC", "NIB", "CIL", "ID", "TPCT", "NOME", "LOCALIDADE", "PRODUTO", "TARIFA", "ESTCTR"]

    dfs = []
    for f in ficheiros:
        df = pd.read_csv(
            f,
            sep="\t",
            header=None,
            usecols=usecols,
            names=names,
            encoding="utf-8",
            quoting=3,  # QuoteStyle.None
            dtype=str,
            on_bad_lines="skip",
        )
        dfs.append(df)

    df_ctr = pd.concat(dfs, ignore_index=True)

    # Tipagem inicial (Int64.Type e type text)
    for col in ["UC", "NIB", "CIL", "ID", "TPCT", "ESTCTR"]:
        df_ctr[col] = pd.to_numeric(df_ctr[col], errors="coerce").astype("Int64")

    for col in ["NOME", "LOCALIDADE", "PRODUTO", "TARIFA"]:
        df_ctr[col] = df_ctr[col].fillna("").astype(str).str.strip()
        df_ctr.loc[df_ctr[col] == "", col] = None

    # ComCIL_ID = Text.From([CIL]) & "," & Text.From([ID])
    df_ctr["CIL_ID"] = df_ctr["CIL"].astype(str) + "," + df_ctr["ID"].astype(str)

    # Inclusão dos Contratos Especiais de Água (E021 - Águas de Santiago S.A.)
    df_ads = pd.DataFrame([
        {
            "UC": 10201000,
            "NIB": 60209538,
            "CIL": 60220187,
            "ID": 60209538,
            "TPCT": 72,
            "NOME": "AGUAS DE SANTIAGO S.A. (AdS - Água)",
            "LOCALIDADE": "PRAIA - SEDE / DISTRIBUIÇÃO",
            "PRODUTO": "AG",
            "TARIFA": "CD",
            "ESTCTR": 10,
            "CIL_ID": "60220187,60209538",
        },
        {
            "UC": 10201000,
            "NIB": 60209538,
            "CIL": 60220188,
            "ID": 60209538,
            "TPCT": 72,
            "NOME": "AGUAS DE SANTIAGO S.A. (AdS - Água)",
            "LOCALIDADE": "PRAIA - SEDE / DISTRIBUIÇÃO",
            "PRODUTO": "AG",
            "TARIFA": "CD",
            "ESTCTR": 10,
            "CIL_ID": "60220188,60209538",
        },
    ])
    df_ctr = pd.concat([df_ctr, df_ads], ignore_index=True)

    print(f"  [1/9] CONTRATO carregado: {len(df_ctr):,} linhas ({time.time() - t0:.2f}s)")
    return df_ctr


# ==============================================================================
# 2. PREPARAÇÃO DEFENSIVA DAS TABELAS DIMENSÃO (COM DEDUPLICAÇÃO 1:1)
# ==============================================================================
def carregar_dimensoes_codigos():
    """Lê Tabela9 (ESTCTR), Tabela10 (TPCT) e Tabela11 (UC) de CODIGOS.xlsx."""
    cod_path = os.path.join(BASE_ATUAL_SCRIPT, "CODIGOS.xlsx")
    if os.path.exists(cod_path):
        wb = openpyxl.load_workbook(cod_path, data_only=True)
        tabelas = {}
        for s in wb.sheetnames:
            ws = wb[s]
            for tname, ref in ws.tables.items():
                if tname in ("Tabela9", "Tabela10", "Tabela11"):
                    rows = [[c.value for c in row] for row in ws[ref]]
                    tabelas[tname] = pd.DataFrame(rows[1:], columns=rows[0])
        wb.close()

        dim_tpct = tabelas["Tabela10"][["COD_CLI", "GRUP_TP_CLI"]].copy()
        dim_tpct["COD_CLI"] = pd.to_numeric(dim_tpct["COD_CLI"], errors="coerce").astype("Int64")
        dim_tpct = dim_tpct.drop_duplicates(subset=["COD_CLI"], keep="first")

        dim_estctr = tabelas["Tabela9"][["Código", "Descrição"]].copy()
        dim_estctr["Código"] = pd.to_numeric(dim_estctr["Código"], errors="coerce").astype("Int64")
        dim_estctr = dim_estctr.drop_duplicates(subset=["Código"], keep="first")

        dim_uc = tabelas["Tabela11"][["COD_UNI", "DESC_UNI", "ILHA"]].copy()
        dim_uc["COD_UNI"] = pd.to_numeric(dim_uc["COD_UNI"], errors="coerce").astype("Int64")
        dim_uc["DESC_UNI"] = dim_uc["DESC_UNI"].fillna("").astype(str).str.strip()
        dim_uc["ILHA"] = dim_uc["ILHA"].fillna("").astype(str).str.strip()
        dim_uc.loc[dim_uc["ILHA"] == "", "ILHA"] = None
        dim_uc = dim_uc.drop_duplicates(subset=["COD_UNI"], keep="first")
        return dim_tpct, dim_estctr, dim_uc

    raise FileNotFoundError(f"Ficheiro CODIGOS.xlsx não encontrado em {cod_path}")


def carregar_dim_divida() -> pd.DataFrame:
    """
    Ingestão DIRETA de Dívida a partir de Atual_script/DIVIDA/*.txt.
    Elimina a dependência de divida_2.xlsx ou Power Query no Excel.
    """
    t0 = time.time()
    pasta_div = os.path.join(BASE_ATUAL_SCRIPT, "DIVIDA")

    if os.path.exists(pasta_div):
        ficheiros = sorted([
            os.path.join(pasta_div, f)
            for f in os.listdir(pasta_div)
            if not f.startswith("~$")
            and not f.startswith(".")
            and f.lower().endswith(".txt")
            and os.path.isfile(os.path.join(pasta_div, f))
        ])
    else:
        ficheiros = []

    if ficheiros:
        dfs = []
        for f in ficheiros:
            df = pd.read_csv(
                f,
                sep="\t",
                header=None,
                usecols=[0, 4, 5, 9, 19, 26],
                names=["EMP_ID", "UNIDADE", "CIL", "CLI_CONTA", "NUMFACT", "VAL_DIVIDA"],
                encoding="latin1",
                quoting=3,
                dtype=str,
                on_bad_lines="skip",
            )
            dfs.append(df)

        df_div = pd.concat(dfs, ignore_index=True)
        df_div["EMP_ID"] = df_div["EMP_ID"].fillna("").astype(str).str.strip().str.lstrip("0")
        ucs_excluir = {
            "010000000", "010101000", "010301000", "010400000", "010401000",
            "010501000", "010502000", "010601000", "010602000", "010603000",
            "010201003", "010201004", "010201002", "010201001",
        }
        df_div = df_div[~df_div["UNIDADE"].fillna("").str.strip().isin(ucs_excluir)].copy()

        for col in ["CIL", "CLI_CONTA"]:
            s = df_div[col].fillna("").str.strip()
            tam = s.str.len()
            df_div[col] = np.where(tam == 5, "600" + s, np.where(tam == 6, "60" + s, s))

        # Garantir apenas CILs de 8 dígitos
        df_div = df_div[df_div["CIL"].str.len() == 8].copy()
        df_div["CIL_ID"] = df_div["CIL"] + "," + df_div["CLI_CONTA"]
        df_div["VAL_DIVIDA"] = pd.to_numeric(
            df_div["VAL_DIVIDA"].str.replace(r"[^0-9,.\-]", "", regex=True), errors="coerce"
        ).fillna(0.0)

        # Vetorização por Empresa (17: EDEC SA, 21: ELECTRA SA, 7: EDEC Sul, 70: ELECTRA SARL)
        df_div["VAL_17"] = np.where(df_div["EMP_ID"] == "17", df_div["VAL_DIVIDA"], 0.0)
        df_div["FAT_17"] = np.where(df_div["EMP_ID"] == "17", 1, 0)
        df_div["VAL_21"] = np.where(df_div["EMP_ID"] == "21", df_div["VAL_DIVIDA"], 0.0)
        df_div["FAT_21"] = np.where(df_div["EMP_ID"] == "21", 1, 0)
        df_div["VAL_7"]  = np.where(df_div["EMP_ID"] == "7",  df_div["VAL_DIVIDA"], 0.0)
        df_div["FAT_7"]  = np.where(df_div["EMP_ID"] == "7",  1, 0)
        df_div["VAL_70"] = np.where(df_div["EMP_ID"] == "70", df_div["VAL_DIVIDA"], 0.0)
        df_div["FAT_70"] = np.where(df_div["EMP_ID"] == "70", 1, 0)

        dim_divida = df_div.groupby("CIL_ID", dropna=False, as_index=False, sort=False).agg(
            VALOR=("VAL_DIVIDA", "sum"),
            QTD=("NUMFACT", "count"),
            divida_edec=("VAL_17", "sum"),
            faturas_edec=("FAT_17", "sum"),
            divida_electra=("VAL_21", "sum"),
            faturas_electra=("FAT_21", "sum"),
            divida_sul=("VAL_7", "sum"),
            faturas_sul=("FAT_7", "sum"),
            divida_sarl=("VAL_70", "sum"),
            faturas_sarl=("FAT_70", "sum"),
        )

        conds = [
            (dim_divida["divida_edec"] >= dim_divida["divida_electra"]) & (dim_divida["divida_edec"] >= dim_divida["divida_sul"]) & (dim_divida["divida_edec"] >= dim_divida["divida_sarl"]) & (dim_divida["divida_edec"] > 0),
            (dim_divida["divida_electra"] >= dim_divida["divida_edec"]) & (dim_divida["divida_electra"] >= dim_divida["divida_sul"]) & (dim_divida["divida_electra"] >= dim_divida["divida_sarl"]) & (dim_divida["divida_electra"] > 0),
            (dim_divida["divida_sul"] >= dim_divida["divida_edec"]) & (dim_divida["divida_sul"] >= dim_divida["divida_electra"]) & (dim_divida["divida_sul"] >= dim_divida["divida_sarl"]) & (dim_divida["divida_sul"] > 0),
            (dim_divida["divida_sarl"] > 0),
        ]
        choices = ["EDEC SA", "ELECTRA SA", "EDEC Sul", "ELECTRA SARL"]
        dim_divida["empresa_predom"] = np.select(conds, choices, default="Sem Dívida")

        print(
            f"  [2/9] Dim_DIVIDA processada direto de Atual_script/DIVIDA: {len(dim_divida):,} CIL_IDs únicos "
            f"[Total: {dim_divida['VALOR'].sum():,.2f} ECV | EDEC: {dim_divida['divida_edec'].sum():,.0f} ECV | "
            f"ELECTRA: {dim_divida['divida_electra'].sum():,.0f} ECV | Sul: {dim_divida['divida_sul'].sum():,.0f} ECV | "
            f"SARL: {dim_divida['divida_sarl'].sum():,.0f} ECV] ({time.time() - t0:.2f}s)"
        )
        return dim_divida

    # Fallback defensivo para arquivo .xlsx se pasta não existir
    divida2_path = os.path.join(BASE_SANTIAGO, "divida_2.xlsx")
    if os.path.exists(divida2_path):
        df_div = pd.read_excel(
            divida2_path,
            sheet_name="Folha1",
            usecols=["CIL", "CLI CONTA", "VAL DIVIDA", "QTD NUMFACT"],
            dtype={"CIL": str, "CLI CONTA": str},
        )
        for col in ["CIL", "CLI CONTA"]:
            s = df_div[col].fillna("").astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
            tam = s.str.len()
            df_div[col] = np.where(tam == 5, "600" + s, np.where(tam == 6, "60" + s, s))

        df_div["CIL_ID"] = df_div["CIL"] + "," + df_div["CLI CONTA"]
        df_div["VAL DIVIDA"] = pd.to_numeric(df_div["VAL DIVIDA"], errors="coerce").fillna(0.0)
        df_div["QTD NUMFACT"] = pd.to_numeric(df_div["QTD NUMFACT"], errors="coerce").fillna(0).astype("int64")

        dim_divida = df_div.groupby("CIL_ID", dropna=False, as_index=False, sort=False).agg(
            VALOR=("VAL DIVIDA", "sum"),
            QTD=("QTD NUMFACT", "sum"),
        )
        print(
            f"  [2/9] Dim_DIVIDA (divida_2.xlsx fallback) processada: {len(dim_divida):,} CIL_IDs únicos "
            f"[Total: {dim_divida['VALOR'].sum():,.2f} ECV] ({time.time() - t0:.2f}s)"
        )
        return dim_divida


def carregar_dim_aparelho() -> pd.DataFrame:
    t0 = time.time()
    pasta_apa = os.path.join(BASE_ATUAL_SCRIPT, "APARELHO")
    ficheiros = sorted([
        os.path.join(pasta_apa, f)
        for f in os.listdir(pasta_apa)
        if not f.startswith("~$")
        and not f.startswith(".")
        and os.path.isfile(os.path.join(pasta_apa, f))
    ])

    dfs = []
    for f in ficheiros:
        df = pd.read_csv(
            f,
            sep="\t",
            header=None,
            usecols=[1, 5, 8, 11, 12, 19, 22, 23],
            names=["UC", "CIL", "DA_INST", "MODELO", "CONTADOR", "Column20", "DATA", "LEITURA"],
            encoding="cp1252",
            quoting=3,
            dtype=str,
            on_bad_lines="skip",
        )
        dfs.append(df)

    df_apa = pd.concat(dfs, ignore_index=True)
    df_apa["UC"] = pd.to_numeric(df_apa["UC"], errors="coerce")
    ucs_excluir = {10101000, 10301000, 10401000, 10501000, 10502000, 10601000, 10602000, 10603000}
    df_apa = df_apa[df_apa["UC"].notna() & (~df_apa["UC"].isin(ucs_excluir))].copy()

    df_apa["CIL"] = pd.to_numeric(df_apa["CIL"], errors="coerce").astype("Int64")
    df_apa = df_apa.drop_duplicates(subset=["CIL"], keep="first").copy()

    df_apa["CONTADOR"] = pd.to_numeric(df_apa["CONTADOR"], errors="coerce").astype("Int64")
    df_apa["LEITURA"] = pd.to_numeric(df_apa["LEITURA"], errors="coerce")
    df_apa["Column20_num"] = pd.to_numeric(df_apa["Column20"], errors="coerce")
    df_apa["MODELO"] = df_apa["MODELO"].fillna("").astype(str).str.strip()
    df_apa.loc[df_apa["MODELO"] == "", "MODELO"] = None

    da_inst_dt = pd.to_datetime(df_apa["DA_INST"].str.strip(), format="%Y%m%d", errors="coerce")
    data_leit_dt = pd.to_datetime(df_apa["DATA"].str.strip(), format="%Y%m%d", errors="coerce")

    df_apa["DA_INST"] = da_inst_dt.dt.strftime("%Y-%m-%d")
    df_apa.loc[da_inst_dt.isna(), "DA_INST"] = None

    df_apa["DATA_LEITURA"] = data_leit_dt.dt.strftime("%Y-%m-%d")
    df_apa.loc[data_leit_dt.isna(), "DATA_LEITURA"] = None

    hoje = pd.Timestamp.today().normalize()
    corte_10_anos = hoje - pd.DateOffset(years=10)
    corte_20_anos = hoje - pd.DateOffset(years=20)
    corte_5_meses = hoje - pd.DateOffset(months=5)

    df_apa["Mat_Contador"] = np.where(
        da_inst_dt >= corte_10_anos,
        "Ate 10 ano",
        np.where(da_inst_dt >= corte_20_anos, "Ate 20 ano", "> 20 ano"),
    )

    df_apa["Mat_Leitura"] = np.where(
        data_leit_dt >= corte_5_meses,
        "< 5 meses",
        "> 5 meses",
    )

    df_apa["tp_fat"] = np.where(df_apa["Column20_num"] == 11, "C/L", "")

    cols_ret = ["CIL", "DA_INST", "DATA_LEITURA", "MODELO", "CONTADOR", "LEITURA", "Mat_Contador", "Mat_Leitura", "tp_fat"]
    print(
        f"  [3/9] Dim_APARELHO processada: {len(df_apa):,} CILs únicos "
        f"[Corte 5m: {corte_5_meses.strftime('%Y-%m-%d')} | 10a: {corte_10_anos.strftime('%Y-%m-%d')}] ({time.time() - t0:.2f}s)"
    )
    return df_apa[cols_ret]


def localizar_ficheiro_mais_recente(pasta: str, prefixos: tuple[str, ...], nome_padrao: str) -> str:
    """Encontra automaticamente o ficheiro .xlsx mais recente que comece com um dos prefixos."""
    caminho_exato = os.path.join(pasta, nome_padrao)
    candidatos = [
        os.path.join(pasta, f)
        for f in os.listdir(pasta)
        if not f.startswith("~$")
        and f.lower().endswith(".xlsx")
        and f.lower().startswith(tuple(p.lower() for p in prefixos))
    ]
    if candidatos:
        candidatos.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        return candidatos[0]
    if os.path.exists(caminho_exato):
        return caminho_exato
    raise FileNotFoundError(f"Nenhum ficheiro encontrado em {pasta} com prefixo {prefixos}")


def carregar_dimensoes_santiago():
    t0 = time.time()
    # Dim_Anomalia
    p_anom = localizar_ficheiro_mais_recente(BASE_SANTIAGO, ("Anomalia",), "Anomalia de Leitura Setembro 2026.xlsx")
    df_anom = pd.read_excel(p_anom, sheet_name=0, usecols=["CIL", "Anomalia"])
    df_anom["CIL"] = pd.to_numeric(df_anom["CIL"], errors="coerce").astype("Int64")
    df_anom = df_anom.drop_duplicates(subset=["CIL"], keep="first").rename(columns={"Anomalia": "Anomalia.1"})

    # Dim_Faturacao
    p_fat = localizar_ficheiro_mais_recente(BASE_SANTIAGO, ("Fat_piv", "Faturacao", "Faturaçao"), "Fat_piv.xlsx")
    df_fat = pd.read_excel(p_fat, sheet_name="FATURAÇAO", usecols=["CIL", "T3", "Alerta_Desvio", "Variação_%"])
    df_fat["CIL"] = pd.to_numeric(df_fat["CIL"], errors="coerce").astype("Int64")
    df_fat["T3"] = pd.to_numeric(df_fat["T3"], errors="coerce")
    df_fat["Variação_%"] = pd.to_numeric(df_fat["Variação_%"], errors="coerce")
    df_fat = df_fat.drop_duplicates(subset=["CIL"], keep="first").rename(
        columns={
            "T3": "FATURAÇAO.T3",
            "Alerta_Desvio": "FATURAÇAO.Alerta_Desvio",
            "Variação_%": "FATURAÇAO.Variação_%",
        }
    )

    # Dim_GEO
    p_geo = localizar_ficheiro_mais_recente(BASE_SANTIAGO, ("CL_PT",), "CL_PT_15_10_26.xlsx")
    df_geo = pd.read_excel(p_geo, sheet_name=0, usecols=["CIL", "lat", "long", "PT"])
    df_geo["CIL"] = pd.to_numeric(df_geo["CIL"], errors="coerce").astype("Int64")
    for c in ["lat", "long", "PT"]:
        df_geo[c] = df_geo[c].astype(str).str.strip()
        df_geo.loc[df_geo[c].isin(["nan", "None", ""]), c] = None
    df_geo = df_geo.drop_duplicates(subset=["CIL"], keep="first")

    # Dim_IMTT
    p_imtt = localizar_ficheiro_mais_recente(BASE_SANTIAGO, ("IMTT",), "IMTT.xlsx")
    df_imtt = pd.read_excel(p_imtt, sheet_name=0, usecols=["CIL", "TIP"])
    df_imtt["CIL"] = pd.to_numeric(df_imtt["CIL"], errors="coerce").astype("Int64")
    df_imtt["TIP"] = df_imtt["TIP"].astype(str).str.strip()
    df_imtt.loc[df_imtt["TIP"].isin(["nan", "None", ""]), "TIP"] = None
    df_imtt = df_imtt.drop_duplicates(subset=["CIL"], keep="first")

    print(
        f"  [4/9] Dimensões base carregadas ({time.time() - t0:.2f}s):\n"
        f"        - Anomalia : {os.path.basename(p_anom)} ({len(df_anom):,} reg.)\n"
        f"        - Faturação: {os.path.basename(p_fat)} ({len(df_fat):,} reg.)\n"
        f"        - GEO / PT : {os.path.basename(p_geo)} ({len(df_geo):,} reg.)\n"
        f"        - IMTT     : {os.path.basename(p_imtt)} ({len(df_imtt):,} reg.)"
    )
    return df_anom, df_fat, df_geo, df_imtt


def carregar_dim_cf1_autos() -> pd.DataFrame:
    """
    Carrega a planilha 'autos' de cf1_aut.xlsx, normalizando estados jurídicos e
    consolidando métricas de Autos de Fraude (CF1) por CIL (Adição).
    """
    t0 = time.time()
    p_cf1 = localizar_ficheiro_mais_recente(BASE_SANTIAGO, ("cf1_aut", "cf1"), "cf1_aut.xlsx")
    df_aut = pd.read_excel(
        p_cf1,
        sheet_name="autos",
        usecols=["Adição", "VAL_TOTAL", "VAL_DIV", "QTD", "Ano", "Estado_Divida", "Estado", "Entregue"],
    )
    df_aut["CIL"] = pd.to_numeric(df_aut["Adição"], errors="coerce").astype("Int64")
    df_aut = df_aut[df_aut["CIL"].notna()].copy()

    df_aut["VAL_TOTAL"] = pd.to_numeric(df_aut["VAL_TOTAL"], errors="coerce").fillna(0.0)
    df_aut["VAL_DIV"] = pd.to_numeric(df_aut["VAL_DIV"], errors="coerce").fillna(0.0)
    df_aut["QTD"] = pd.to_numeric(df_aut["QTD"], errors="coerce").fillna(0.0)
    df_aut["Ano"] = pd.to_numeric(df_aut["Ano"], errors="coerce").fillna(0).astype("int64")

    # Normalização de Estado Jurídico (Base)
    est_raw = df_aut["Estado"].fillna("").astype(str).str.strip()
    est_lower = est_raw.str.lower()
    df_aut["Estado_Norm"] = np.where(
        est_lower.isin(["a enviar ao mp", "enviar ao mp"]),
        "A enviar ao MP",
        np.where(
            est_lower == "enviado ao mp",
            "Enviado ao MP",
            np.where(
                est_lower.str.contains("dnice"),
                "Enviado à DNICE",
                np.where(est_raw == "", "Sem Processo Base", est_raw),
            ),
        ),
    )

    ent_raw = df_aut["Entregue"].fillna("").astype(str).str.strip()
    df_aut["Entregue_Norm"] = np.where(ent_raw == "", "Não Informado", ent_raw)

    est_div_raw = df_aut["Estado_Divida"].fillna("").astype(str).str.strip()
    df_aut["Estado_Divida_Norm"] = np.where(est_div_raw == "", "Não Informado", est_div_raw)

    # Ordenar por Ano decrescente e VAL_DIV decrescente para que o primeiro registo de cada CIL
    # reflita o auto mais recente / com dívida ativa
    df_aut = df_aut.sort_values(by=["CIL", "Ano", "VAL_DIV"], ascending=[True, False, False])

    dim_cf1 = df_aut.groupby("CIL", as_index=False, sort=False).agg(
        cf1_qtd_autos=("CIL", "count"),
        cf1_kwh_total=("QTD", "sum"),
        cf1_val_total=("VAL_TOTAL", "sum"),
        cf1_val_divida=("VAL_DIV", "sum"),
        cf1_ultimo_ano=("Ano", "max"),
        cf1_estado_divida=("Estado_Divida_Norm", "first"),
        cf1_estado_juridico=("Estado_Norm", "first"),
        cf1_evidencia_fotos=("Entregue_Norm", "first"),
    )

    dim_cf1["cf1_kwh_total"] = dim_cf1["cf1_kwh_total"].round(2)
    dim_cf1["cf1_val_total"] = dim_cf1["cf1_val_total"].round(2)
    dim_cf1["cf1_val_divida"] = dim_cf1["cf1_val_divida"].round(2)

    print(
        f"  [5/9] Dim_CF1_AUTOS ({os.path.basename(p_cf1)}) processada: {len(dim_cf1):,} CILs c/ auto "
        f"[{dim_cf1['cf1_qtd_autos'].sum():,} autos | Dívida CF1: {dim_cf1['cf1_val_divida'].sum():,.0f} ECV] ({time.time() - t0:.2f}s)"
    )
    return dim_cf1


def carregar_dim_cobranca() -> pd.DataFrame:
    """
    Ingestão DIRETA de alta performance a partir de Atual_script/cob_26/*.txt.
    Substitui 100% a dependência de COB_J.xlsx ou Power Query no Excel.
    
    Regras de Negócio Blindadas:
    1. Filtra UCs de outras ilhas (São Vicente 0101, Santo Antão 0103, Sal 0105, BV 0106).
    2. Exclui linhas sem UC ('00') ou sem CIL ('00'), eliminando duplicações em Maio e Junho.
    3. Exclui tipo 'XX' (lançamentos de caixa VCI/Pré-pago sem contrato de fatura pós-paga).
    4. Exige CILs estritamente com 8 dígitos numéricos (10000000 a 99999999).
    5. Calcula meses pagos reais (>0 ECV) e maturidade predominante em atraso.
    """
    t0 = time.time()
    pasta_cob = os.path.join(BASE_ATUAL_SCRIPT, "cob_26")
    
    # Se a pasta cob_26 não existir, faz fallback defensivo para ficheiro .xlsx
    if not os.path.exists(pasta_cob):
        p_cob = localizar_ficheiro_mais_recente(BASE_SANTIAGO, ("COB_J", "COB"), "COB_J.xlsx")
        df_cob = pd.read_excel(
            p_cob,
            sheet_name="CB_J",
            usecols=["cil_", "Nome do Mês.1", "MATURIDADE_", "VALOR"],
            dtype={"cil_": str},
        )
        s_cil = df_cob["cil_"].fillna("").astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
        df_cob = df_cob[s_cil.str.len() == 8].copy()
        df_cob["CIL"] = pd.to_numeric(s_cil[s_cil.str.len() == 8], errors="coerce").astype("Int64")
        df_cob["VALOR"] = pd.to_numeric(df_cob["VALOR"], errors="coerce").fillna(0.0)
        df_cob["mes_str"] = df_cob["Nome do Mês.1"].fillna("").astype(str).str.strip().str.lower()
        df_cob["mat_str"] = df_cob["MATURIDADE_"].fillna("Sem Data").astype(str).str.strip()
        ordem_mes = {
            "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
            "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
            "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
        }
        df_cob["mes_num"] = df_cob["mes_str"].map(ordem_mes).fillna(0).astype("int32")
        df_all = df_cob[["CIL", "mes_num", "mat_str", "VALOR"]].copy()
    else:
        ficheiros = sorted([
            os.path.join(pasta_cob, f)
            for f in os.listdir(pasta_cob)
            if f.lower().endswith(".txt") and not f.startswith(".") and not f.startswith("~$")
        ])
        
        ucs_excluir = {"010101000", "010301000", "010501000", "010502000", "010601000", "010602000", "010603000"}
        
        dfs = []
        for fp in ficheiros:
            df = pd.read_csv(
                fp, sep="\t", header=None, usecols=[0, 1, 8, 11, 16, 21],
                names=["UC", "CIL", "DATA_COBR", "VALOR", "TIPO_DOC", "data_fat"],
                dtype=str, quoting=3, encoding="latin1", on_bad_lines="skip"
            )
            uc = df["UC"].fillna("").str.strip()
            df["UC"] = np.where(uc == "", "00", uc.str.zfill(9))
            cil = df["CIL"].fillna("").str.strip()
            tipo = df["TIPO_DOC"].fillna("").str.strip().str.upper()
            
            # Filtro defensivo: UC de Santiago, não XX, CIL de 8 dígitos estritos
            mask = (
                (df["UC"] != "00")
                & (~df["UC"].isin(ucs_excluir))
                & (tipo != "XX")
                & (cil.str.len() == 8)
                & cil.str.isdigit()
            )
            df = df[mask].copy()
            
            df["VALOR"] = pd.to_numeric(
                df["VALOR"].str.replace(r"[^0-9,.\-]", "", regex=True), errors="coerce"
            ).fillna(0.0)
            dc = pd.to_datetime(df["DATA_COBR"].str.strip(), format="%Y%m%d", errors="coerce")
            dfat = pd.to_datetime(df["data_fat"].str.strip(), format="%Y%m%d", errors="coerce")
            dias = (dc - dfat).dt.days
            
            df["mat_str"] = np.select(
                [dias.isna() | (dias < 0), dias < 31, dias < 61, dias < 91, dias < 181, dias < 361],
                ["Sem Data", "1 mes", "2 mes", "3 mes", "6 mes", "1 ano"],
                "> 1 ano"
            )
            df["mes_num"] = dc.dt.month.fillna(0).astype("int32")
            df["CIL"] = pd.to_numeric(df["CIL"], errors="coerce").astype("Int64")
            df = df[df["CIL"].notna() & (df["mes_num"] > 0)]
            
            # Pré-agrupamento por ficheiro para manter pegada de memória levíssima
            dfs.append(df.groupby(["CIL", "mes_num", "mat_str"], as_index=False, sort=False)["VALOR"].sum())
        
        df_all = pd.concat(dfs, ignore_index=True)
        df_all = df_all.groupby(["CIL", "mes_num", "mat_str"], as_index=False, sort=False)["VALOR"].sum()

    inv_mes = {
        1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
        5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
        9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
    }
    mat_atraso = {"3 mes", "6 mes", "1 ano", "> 1 ano"}
    df_all["val_atraso"] = np.where(df_all["mat_str"].isin(mat_atraso), df_all["VALOR"], 0.0)

    # 1. Total e Atraso por CIL
    dim_cob = df_all.groupby("CIL", as_index=False, sort=False).agg(
        cob_valor_total=("VALOR", "sum"),
        cob_valor_atraso=("val_atraso", "sum"),
    )
    dim_cob["cob_valor_total"] = dim_cob["cob_valor_total"].round(2)
    dim_cob["cob_valor_atraso"] = np.maximum(0.0, dim_cob["cob_valor_atraso"]).round(2)

    # 2. Meses com soma líquida positiva
    df_mes = df_all.groupby(["CIL", "mes_num"], as_index=False, sort=False)["VALOR"].sum()
    df_mes_pos = df_mes[df_mes["VALOR"] > 0]
    df_mes_agg = df_mes_pos.groupby("CIL", as_index=False, sort=False).agg(
        cob_qtd_meses=("mes_num", "nunique"),
        max_mes_num=("mes_num", "max"),
    )
    df_mes_agg["cob_ultimo_mes"] = df_mes_agg["max_mes_num"].map(inv_mes)

    # 3. Maturidade predominante (>0 ECV)
    df_mat = df_all.groupby(["CIL", "mat_str"], as_index=False, sort=False)["VALOR"].sum()
    df_mat_pos = (
        df_mat[df_mat["VALOR"] > 0]
        .sort_values(by=["CIL", "VALOR"], ascending=[True, False])
        .drop_duplicates(subset=["CIL"], keep="first")
        .rename(columns={"mat_str": "cob_maturidade_predom"})[["CIL", "cob_maturidade_predom"]]
    )

    dim_cob = (
        dim_cob.merge(df_mes_agg[["CIL", "cob_qtd_meses", "cob_ultimo_mes"]], on="CIL", how="left")
        .merge(df_mat_pos, on="CIL", how="left")
    )
    dim_cob["cob_qtd_meses"] = dim_cob["cob_qtd_meses"].fillna(0).astype("int64")

    # Se o total líquido no ano for <= 0, limpa meses e maturidade
    mask_sem_pag = dim_cob["cob_valor_total"] <= 0
    dim_cob.loc[mask_sem_pag, "cob_qtd_meses"] = 0
    dim_cob.loc[mask_sem_pag, "cob_ultimo_mes"] = None
    dim_cob.loc[mask_sem_pag, "cob_maturidade_predom"] = None

    pagadores_pos = (dim_cob["cob_valor_total"] > 0).sum()
    soma_pos = dim_cob.loc[dim_cob["cob_valor_total"] > 0, "cob_valor_total"].sum()
    print(
        f"  [6/9] Dim_COBRANCA processada direto de Atual_script/cob_26: {pagadores_pos:,} CILs pagadores (>0 ECV) "
        f"[Total Cobrado: {soma_pos:,.0f} ECV] ({time.time() - t0:.2f}s)"
    )
    return dim_cob


def calcular_score_risco(df: pd.DataFrame) -> pd.DataFrame:
    """
    Motor Eletrotécnico, Comercial e Jurídico de Score de Risco de Fraude / Perdas (0 a 100).
    Combina Anomalias de Leitura, Incoerência Contratual, Desvio de Faturação (T3),
    Maturidade de Leitura/Contador, Histórico/Reincidência de Autos CF1 e Comportamento de Cobrança.
    """
    n = len(df)
    score = np.zeros(n, dtype=np.int32)

    anom = df["Anomalia.1"].fillna("").astype(str).str.strip()
    est = df["EST_CTR"].fillna("").astype(str).str.strip()
    desvio = df["FATURAÇAO.Alerta_Desvio"].fillna("").astype(str).str.strip()
    t3 = pd.to_numeric(df["FATURAÇAO.T3"], errors="coerce").fillna(0)
    var_pct = pd.to_numeric(df["FATURAÇAO.Variação_%"], errors="coerce").fillna(0)
    mat_leit = df["Mat_Leitura"].fillna("").astype(str).str.strip()
    mat_cont = df["Mat_Contador"].fillna("").astype(str).str.strip()
    tem_contador = df["CONTADOR"].notna()
    grupo = df["GRUP_TP_CLI"].fillna("").astype(str).str.strip()
    valor = pd.to_numeric(df["VALOR"], errors="coerce").fillna(0)
    qtd_fat = pd.to_numeric(df["QTD"], errors="coerce").fillna(0)

    cf1_qtd = pd.to_numeric(df["cf1_qtd_autos"], errors="coerce").fillna(0).astype(int)
    cf1_div = pd.to_numeric(df["cf1_val_divida"], errors="coerce").fillna(0)
    status_cob = df["status_cobranca"].fillna("").astype(str).str.strip()

    # 1. ANOMALIAS DE LEITURA (Peso até 50 pts)
    anom_fraude = {
        "Suspeita de Fraude",
        "Ligado Directo",
        "Local de Consumo Sem Contador",
        "Sem Selos de Invólucro",
        "Falta Selo no Aparelho",
        "Contador Parado Local Habitado",
    }
    anom_avaria = {
        "Contador Cortado",
        "Display Apagado",
        "Funções Congeladas",
        "Contador Desconhecido",
        "Aparelho Avariado",
        "Contador Parado",
        "Contador Subst. Sem Tratamento",
        "Número do Aparelho Errado",
        "Dispositivo Quebrado",
        "Aparelho Queimado",
    }
    anom_acesso = {
        "Leitura Impossível",
        "Leitura Difícil",
        "Além da Escada",
        "Não Comunica - sem Leitura",
    }

    m_fraude = anom.isin(anom_fraude)
    m_avaria = anom.isin(anom_avaria)
    m_acesso = anom.isin(anom_acesso)
    m_outra_anom = (anom != "") & (~m_fraude) & (~m_avaria) & (~m_acesso)

    score += np.where(m_fraude, 50, np.where(m_avaria, 35, np.where(m_acesso, 20, np.where(m_outra_anom, 12, 0))))

    # 2. INCOERÊNCIA ESTADO CONTRATUAL VS CONSUMO / INSPEÇÃO (Peso até 35 pts)
    em_vigor = est == "Contrato em Vigor"
    inativo_com_consumo = (~em_vigor) & (est != "") & ((t3 > 0) | m_fraude)
    est_inspecao = est.isin({
        "Suspenso por inspecção",
        "Pend. Suspensão por Inspecção",
        "Baixa por Inspec. não Aprovada",
        "Pend. Bai. Inspec não Aprovada",
        "Reactivado de Inspecção",
    })
    vigor_sem_contador = em_vigor & (~tem_contador)

    score += np.where(inativo_com_consumo, 35, 0)
    score += np.where(est_inspecao & (~inativo_com_consumo), 22, 0)
    score += np.where(vigor_sem_contador, 25, 0)

    # 3. DESVIO DE FATURAÇÃO E QUEDA ABRUPTA (Peso até 25 pts)
    tem_desvio = desvio == "Desv_Fat"
    desvio_zero = tem_desvio & em_vigor & (t3 == 0)
    queda_severa = tem_desvio & (var_pct < -0.5) & (~desvio_zero)
    desvio_outro = tem_desvio & (~desvio_zero) & (~queda_severa)

    score += np.where(desvio_zero, 25, np.where(queda_severa, 18, np.where(desvio_outro, 12, 0)))

    # 4. HISTÓRICO E REINCIDÊNCIA DE AUTOS DE FRAUDE CF1 (Peso até 25 pts)
    cf1_reincidente = cf1_qtd >= 2
    cf1_com_divida_ou_risco = (cf1_qtd == 1) & ((cf1_div > 0) | tem_desvio | (anom != ""))
    cf1_historico_simples = (cf1_qtd == 1) & (~cf1_com_divida_ou_risco)

    score += np.where(cf1_reincidente, 25, np.where(cf1_com_divida_ou_risco, 18, np.where(cf1_historico_simples, 10, 0)))

    # 5. MATURIDADE DE LEITURA E OBSOLESCÊNCIA DO CONTADOR (Peso até 20 pts)
    sem_leit_5m = mat_leit == "> 5 meses"
    cont_20a = mat_cont == "> 20 ano"

    score += np.where(sem_leit_5m, 12, 0)
    score += np.where(cont_20a, 8, 0)

    # 6. AGRAVANTE COMERCIAL / INADIMPLÊNCIA SEM COBRANÇA 2026 (Peso até 20 pts)
    nao_domestico = grupo.isin({"Empresa Privada", "Empresa Publica", "Estado", "Autarquia"})
    agravante_comercial = nao_domestico & (tem_desvio | (anom != "") | vigor_sem_contador | (cf1_qtd > 0))
    divida_critica = (valor >= 50000) | (qtd_fat >= 6)
    sem_pag_2026_crit = (status_cob == "Devedor Sem Pagamento 2026") & (valor >= 25000)

    score += np.where(agravante_comercial, 10, 0)
    score += np.where(divida_critica, 8, 0)
    score += np.where(sem_pag_2026_crit, 8, 0)

    score = np.clip(score, 0, 100)

    # Nível de Risco
    nivel = np.where(
        score >= 60,
        "CRÍTICO",
        np.where(score >= 40, "ALTO", np.where(score >= 20, "MÉDIO", "BAIXO")),
    )

    # Construir diagnóstico explicável vetorizado por partes
    partes = pd.Series("", index=df.index, dtype=str)

    def anexar(mask, texto):
        nonlocal partes
        partes = np.where(mask, np.where(partes == "", texto, partes + " + " + texto), partes)

    anexar(m_fraude | m_avaria | m_acesso | m_outra_anom, "Anomalia: " + anom)
    anexar(cf1_reincidente, "Reincidente CF1 (" + cf1_qtd.astype(str) + " autos)")
    anexar(cf1_com_divida_ou_risco, "Auto Fraude CF1 Ativo")
    anexar(cf1_historico_simples, "Histórico Auto CF1")
    anexar(inativo_com_consumo, "Consumo/Fraude em Contrato Inativo")
    anexar(est_inspecao & (~inativo_com_consumo), "Histórico Inspeção")
    anexar(vigor_sem_contador, "Contrato Vigor s/ Contador")
    anexar(desvio_zero, "Desv_Fat (T3=0 kWh)")
    anexar(queda_severa, "Queda Faturação >50%")
    anexar(desvio_outro, "Desv_Fat")
    anexar(sem_leit_5m, "Sem Leitura >5m")
    anexar(cont_20a, "Contador >20a")
    anexar(agravante_comercial, "Cliente Não-Doméstico")
    anexar(divida_critica, "Dívida Elevada")
    anexar(sem_pag_2026_crit, "Sem Pagamento 2026")

    df["Score_Risco"] = score
    df["Nivel_Risco"] = nivel
    df["Motivo_Risco"] = pd.Series(partes, index=df.index).replace("", "Normal / Sem Indícios")
    return df


def atribuir_criterio_perdas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Atribui de forma dinâmica e automática o valor 'y' (elegível para fiscalização de perdas)
    aos consumidores que apresentam pelo menos um dos parâmetros de risco:
    1. Contador Obsoleto (> 20 anos)
    2. Anomalias Graves/Críticas de Leitura e Campo
    3. Contrato Desativado com Suspeita (Baixa por Dívida, Rescisão, etc.)
    4. Reincidência de Autos de Fraude (cf1_qtd_autos > 0)
    5. Score de Risco Elevado (Score >= 40 ou Nível CRÍTICO / ALTO)
    
    Apenas consumidores sem nenhum parâmetro de risco permanecem sem marcação (None).
    """
    col_anom = next((col for col in df.columns if "Anomalia" in col), "Anomalia.1")
    anom = df[col_anom].fillna("").astype(str).str.strip() if col_anom in df.columns else pd.Series("", index=df.index)
    est = df["EST_CTR"].fillna("").astype(str).str.strip() if "EST_CTR" in df.columns else pd.Series("", index=df.index)
    mat_cont = df["Mat_Contador"].fillna("").astype(str).str.strip() if "Mat_Contador" in df.columns else pd.Series("", index=df.index)
    score = pd.to_numeric(df.get("Score_Risco", 0), errors="coerce").fillna(0)
    cf1_qtd = pd.to_numeric(df.get("cf1_qtd_autos", 0), errors="coerce").fillna(0)
    nivel = df.get("Nivel_Risco", pd.Series("", index=df.index)).fillna("").astype(str).str.upper()

    anomalias_criticas = [
        "Suspeita de Fraude", "Ligado Directo", "Display Apagado", "Contador Cortado",
        "Local de Consumo Sem Contador", "Leitura Impossível", "Aparelho Queimado",
        "Aparelho Avariado", "Dispositivo Quebrado", "Sem Selos de Invólucro",
        "Falta Selo no Aparelho", "Não Comunica - sem Leitura", "Não Comunica - com Leitura",
        "Funções Congeladas", "Número do Aparelho Errado", "Contador Parado"
    ]
    
    mascara_risco = (
        (mat_cont == "> 20 ano") |
        (anom.isin(anomalias_criticas)) |
        (est.isin(["Baixa por Dívida", "Rescisão Voluntária", "Baixa Forçada", "Baixa por Inspec. não Aprovada"])) |
        (cf1_qtd > 0) |
        (score >= 40) |
        (nivel.str.contains("CRÍTICO", na=False)) |
        (nivel == "ALTO")
    )
    
    df["Criterio"] = np.where(mascara_risco, "y", None)
    return df


# ==============================================================================
# 3. PIPELINE PRINCIPAL (FILTRAGEM SANTIAGO + JOINS DEFENSIVOS + SCORE RISCO)
# ==============================================================================
def executar_transformacao(manter_duplicados_cil: bool = False) -> pd.DataFrame:
    t_inicio = time.time()
    print("=" * 72)
    print(" INICIANDO PIPELINE ETL - CONTRATOS SANTIAGO (EDEC)")
    print("=" * 72)

    df_ctr = carregar_contratos()
    dim_tpct, dim_estctr, dim_uc = carregar_dimensoes_codigos()
    dim_divida = carregar_dim_divida()
    dim_aparelho = carregar_dim_aparelho()
    dim_anomalia, dim_faturacao, dim_geo, dim_imtt = carregar_dimensoes_santiago()
    dim_cf1 = carregar_dim_cf1_autos()
    dim_cob = carregar_dim_cobranca()

    # 4. CRUZAMENTO COM UC E FILTRAGEM DO UNIVERSO EDEC (SANTIAGO, FOGO, MAIO, BRAVA)
    t0 = time.time()
    df = df_ctr.merge(dim_uc, left_on="UC", right_on="COD_UNI", how="left")

    ilhas_edec = {"Santiago", "Fogo", "Maio", "Brava"}
    df = df[df["ILHA"].isin(ilhas_edec)].copy()
    print(f"  [4/9] Universo EDEC filtrado (Santiago, Fogo, Maio, Brava): {len(df):,} contratos ({time.time() - t0:.2f}s)")

    # 5. ENRIQUECIMENTO DE DADOS (JOINS DEFENSIVOS 1:1)
    df = df.merge(dim_tpct, left_on="TPCT", right_on="COD_CLI", how="left")
    df = df.merge(dim_estctr, left_on="ESTCTR", right_on="Código", how="left").rename(columns={"Descrição": "EST_CTR"})
    df = df.merge(dim_divida, on="CIL_ID", how="left")
    for c_emp in ["divida_edec", "divida_electra", "divida_sul", "divida_sarl"]:
        if c_emp in df.columns:
            df[c_emp] = pd.to_numeric(df[c_emp], errors="coerce").fillna(0.0)
    for c_fat in ["faturas_edec", "faturas_electra", "faturas_sul", "faturas_sarl"]:
        if c_fat in df.columns:
            df[c_fat] = pd.to_numeric(df[c_fat], errors="coerce").fillna(0).astype("int64")
    if "empresa_predom" in df.columns:
        df["empresa_predom"] = df["empresa_predom"].fillna("Sem Dívida")
    df = df.merge(dim_aparelho, on="CIL", how="left")
    df = df.merge(dim_anomalia, on="CIL", how="left")
    df = df.merge(dim_faturacao, on="CIL", how="left")
    df = df.merge(dim_geo, on="CIL", how="left")
    df = df.merge(dim_imtt, on="CIL", how="left")
    df = df.merge(dim_cf1, on="CIL", how="left")
    df = df.merge(dim_cob, on="CIL", how="left")

    # Preencher valores padrão numéricos de CF1 e Cobrança
    df["cf1_qtd_autos"] = pd.to_numeric(df["cf1_qtd_autos"], errors="coerce").fillna(0).astype("int64")
    df["cf1_kwh_total"] = pd.to_numeric(df["cf1_kwh_total"], errors="coerce").fillna(0.0)
    df["cf1_val_total"] = pd.to_numeric(df["cf1_val_total"], errors="coerce").fillna(0.0)
    df["cf1_val_divida"] = pd.to_numeric(df["cf1_val_divida"], errors="coerce").fillna(0.0)
    df["cf1_ultimo_ano"] = pd.to_numeric(df["cf1_ultimo_ano"], errors="coerce").astype("Int64")

    df["cob_valor_total"] = pd.to_numeric(df["cob_valor_total"], errors="coerce").fillna(0.0)
    df["cob_qtd_meses"] = pd.to_numeric(df["cob_qtd_meses"], errors="coerce").fillna(0).astype("int64")
    df["cob_valor_atraso"] = pd.to_numeric(df["cob_valor_atraso"], errors="coerce").fillna(0.0)

    # Classificação de Status de Cobrança 2026 cruzado com Dívida Atual
    val_div_atual = pd.to_numeric(df["VALOR"], errors="coerce").fillna(0.0)
    val_cob_2026 = df["cob_valor_total"]

    df["status_cobranca"] = np.where(
        (val_div_atual > 0) & (val_cob_2026 <= 0),
        "Devedor Sem Pagamento 2026",
        np.where(
            (val_div_atual > 0) & (val_cob_2026 > 0),
            "Devedor em Amortização",
            np.where(
                (val_div_atual <= 0) & (val_cob_2026 > 0),
                "Regular Adimplente",
                "Sem Movimento",
            ),
        ),
    )

    # 6. CÁLCULO SEGURO DA MÉDIA DE FATURAÇÃO + MOTOR DE SCORE DE RISCO
    t3_vals = pd.to_numeric(df["FATURAÇAO.T3"], errors="coerce").fillna(0)
    df["Med_Fat"] = np.where(t3_vals > 0, np.ceil(t3_vals / 3.0), 0).astype("int64")

    if not manter_duplicados_cil:
        df = df.drop_duplicates(subset=["CIL"], keep="first").copy()

    df = calcular_score_risco(df)
    df = atribuir_criterio_perdas(df)

    # 7. SELEÇÃO FINAL DAS COLUNAS (TABELA DE FATOS FINAL)
    colunas_finais = [
        "ILHA", "DESC_UNI", "NIB", "CIL", "ID", "NOME", "LOCALIDADE",
        "EST_CTR", "GRUP_TP_CLI", "PRODUTO", "TARIFA", "CIL_ID",
        "VALOR", "QTD", "DA_INST", "DATA_LEITURA", "MODELO", "CONTADOR", "LEITURA",
        "Mat_Contador", "Mat_Leitura", "tp_fat",
        "Anomalia.1", "FATURAÇAO.T3", "FATURAÇAO.Alerta_Desvio", "FATURAÇAO.Variação_%", "Med_Fat",
        "lat", "long", "PT", "TIP",
        "cf1_qtd_autos", "cf1_kwh_total", "cf1_val_total", "cf1_val_divida",
        "cf1_ultimo_ano", "cf1_estado_divida", "cf1_estado_juridico", "cf1_evidencia_fotos",
        "cob_valor_total", "cob_qtd_meses", "cob_ultimo_mes", "cob_maturidade_predom",
        "cob_valor_atraso", "status_cobranca",
        "divida_edec", "faturas_edec", "divida_electra", "faturas_electra", "divida_sul", "faturas_sul", "divida_sarl", "faturas_sarl", "empresa_predom",
        "Score_Risco", "Nivel_Risco", "Motivo_Risco", "Criterio",
    ]
    df = df[colunas_finais].copy()

    crit_cnt = (df["Nivel_Risco"] == "CRÍTICO").sum()
    alto_cnt = (df["Nivel_Risco"] == "ALTO").sum()
    cf1_cnt = (df["cf1_qtd_autos"] > 0).sum()
    sem_pag_cnt = (df["status_cobranca"] == "Devedor Sem Pagamento 2026").sum()
    print(
        f"  [7/9] Joins e Score de Risco concluídos: {len(df):,} contratos de Santiago\n"
        f"        -> Risco Crítico: {crit_cnt:,} | Alto: {alto_cnt:,}\n"
        f"        -> Clientes c/ Auto CF1: {cf1_cnt:,} | Devedores s/ Pagamento 2026: {sem_pag_cnt:,}\n"
        f"        -> Tempo Joins: {time.time() - t0:.2f}s | Total ETL: {time.time() - t_inicio:.2f}s"
    )
    return df


# ==============================================================================
# 4. EXPORTAÇÃO LOCAL E CARGA EM LOTE PARALELA NO SUPABASE
# ==============================================================================
def exportar_csv_local(df: pd.DataFrame) -> str:
    t0 = time.time()
    out_csv = os.path.join(BASE_SANTIAGO, "santiago_consolidado.csv")
    df.to_csv(out_csv, sep=";", index=False, encoding="utf-8-sig")
    # Etapa 2: Guardar cópia histórica mensal comprimida em backups/santiago_AAAAMM.csv.gz
    pasta_bkp = os.path.join(BASE_SANTIAGO, "backups")
    os.makedirs(pasta_bkp, exist_ok=True)
    tag_mes = datetime.now().strftime("%Y%m")
    out_gz = os.path.join(pasta_bkp, f"santiago_{tag_mes}.csv.gz")
    df.to_csv(out_gz, sep=";", index=False, encoding="utf-8-sig", compression="gzip")
    print(f"  [8/9] CSV local salvo ({out_csv}) + arquivo mensal ({out_gz}) ({time.time() - t0:.2f}s)")
    return out_csv


def preparar_registos_supabase(df: pd.DataFrame) -> list[dict]:
    """Converte o DataFrame para lista de dicionários JSON-safe para o PostgREST."""
    col_t3 = next((c for c in df.columns if "FATURA" in c.upper() and "T3" in c.upper()), "FATURAÇAO.T3")
    col_desv = next((c for c in df.columns if "FATURA" in c.upper() and "ALERTA" in c.upper()), "FATURAÇAO.Alerta_Desvio")
    col_var = next((c for c in df.columns if "FATURA" in c.upper() and ("VAR" in c.upper() or "%" in c)), "FATURAÇAO.Variação_%")
    col_anom = next((c for c in df.columns if "Anomalia" in c), "Anomalia.1")

    df_db = pd.DataFrame({
        "cil": pd.to_numeric(df["CIL"], errors="coerce").astype("Int64"),
        "ilha": df["ILHA"],
        "desc_uni": df["DESC_UNI"],
        "nib": pd.to_numeric(df["NIB"], errors="coerce").astype("Int64"),
        "id_cliente": pd.to_numeric(df["ID"], errors="coerce").astype("Int64"),
        "nome": df["NOME"],
        "localidade": df["LOCALIDADE"],
        "est_ctr": df["EST_CTR"],
        "grup_tp_cli": df["GRUP_TP_CLI"],
        "produto": df["PRODUTO"],
        "tarifa": df["TARIFA"],
        "cil_id": df["CIL_ID"],
        "divida_edec": pd.to_numeric(df["divida_edec"], errors="coerce").fillna(0.0) if "divida_edec" in df.columns else 0.0,
        "faturas_edec": pd.to_numeric(df["faturas_edec"], errors="coerce").fillna(0).astype("Int64") if "faturas_edec" in df.columns else 0,
        "divida_electra": pd.to_numeric(df["divida_electra"], errors="coerce").fillna(0.0) if "divida_electra" in df.columns else 0.0,
        "faturas_electra": pd.to_numeric(df["faturas_electra"], errors="coerce").fillna(0).astype("Int64") if "faturas_electra" in df.columns else 0,
        "divida_sul": pd.to_numeric(df["divida_sul"], errors="coerce").fillna(0.0) if "divida_sul" in df.columns else 0.0,
        "faturas_sul": pd.to_numeric(df["faturas_sul"], errors="coerce").fillna(0).astype("Int64") if "faturas_sul" in df.columns else 0,
        "divida_sarl": pd.to_numeric(df["divida_sarl"], errors="coerce").fillna(0.0) if "divida_sarl" in df.columns else 0.0,
        "faturas_sarl": pd.to_numeric(df["faturas_sarl"], errors="coerce").fillna(0).astype("Int64") if "faturas_sarl" in df.columns else 0,
        "empresa_predom": df["empresa_predom"] if "empresa_predom" in df.columns else None,
        "valor": pd.to_numeric(df["VALOR"], errors="coerce"),
        "qtd": pd.to_numeric(df["QTD"], errors="coerce").astype("Int64"),
        "da_inst": df["DA_INST"],
        "data_leitura": df["DATA_LEITURA"],
        "modelo": df["MODELO"],
        "contador": pd.to_numeric(df["CONTADOR"], errors="coerce").astype("Int64"),
        "leitura": pd.to_numeric(df["LEITURA"], errors="coerce"),
        "mat_contador": df["Mat_Contador"],
        "mat_leitura": df["Mat_Leitura"],
        "tp_fat": df["tp_fat"],
        "anomalia": df[col_anom] if col_anom in df.columns else None,
        "faturacao_t3": pd.to_numeric(df[col_t3], errors="coerce") if col_t3 in df.columns else None,
        "faturacao_alerta_desvio": df[col_desv] if col_desv in df.columns else None,
        "faturacao_variacao_pct": pd.to_numeric(df[col_var], errors="coerce") if col_var in df.columns else None,
        "med_fat": pd.to_numeric(df["Med_Fat"], errors="coerce").astype("Int64"),
        "lat": df["lat"],
        "long": df["long"],
        "pt": df["PT"],
        "tip": df["TIP"],
        "cf1_qtd_autos": pd.to_numeric(df["cf1_qtd_autos"], errors="coerce").fillna(0).astype("Int64"),
        "cf1_kwh_total": pd.to_numeric(df["cf1_kwh_total"], errors="coerce").fillna(0.0),
        "cf1_val_total": pd.to_numeric(df["cf1_val_total"], errors="coerce").fillna(0.0),
        "cf1_val_divida": pd.to_numeric(df["cf1_val_divida"], errors="coerce").fillna(0.0),
        "cf1_ultimo_ano": pd.to_numeric(df["cf1_ultimo_ano"], errors="coerce").astype("Int64"),
        "cf1_estado_divida": df["cf1_estado_divida"],
        "cf1_estado_juridico": df["cf1_estado_juridico"],
        "cf1_evidencia_fotos": df["cf1_evidencia_fotos"],
        "cob_valor_total": pd.to_numeric(df["cob_valor_total"], errors="coerce").fillna(0.0),
        "cob_qtd_meses": pd.to_numeric(df["cob_qtd_meses"], errors="coerce").fillna(0).astype("Int64"),
        "cob_ultimo_mes": df["cob_ultimo_mes"],
        "cob_maturidade_predom": df["cob_maturidade_predom"],
        "cob_valor_atraso": pd.to_numeric(df["cob_valor_atraso"], errors="coerce").fillna(0.0),
        "status_cobranca": df["status_cobranca"],
        "score_risco": pd.to_numeric(df["Score_Risco"], errors="coerce").fillna(0).astype("Int64"),
        "nivel_risco": df["Nivel_Risco"],
        "motivo_risco": df["Motivo_Risco"],
        "criterio": df["Criterio"] if "Criterio" in df.columns else None,
    })
    # Remover linhas sem CIL
    df_db = df_db[df_db["cil"].notna()].copy()
    # Converter para JSON e recarregar substitui qualquer NaN/NA por None nativo em C!
    return json.loads(df_db.to_json(orient="records"))


def chave_escrita_valida() -> bool:
    """Confirma que SUPABASE_SERVICE_KEY existe e não é a chave anon (pública)."""
    if not SUPABASE_SERVICE_KEY:
        return False
    if SUPABASE_SERVICE_KEY.startswith("sb_secret_"):
        return True
    try:
        import base64
        payload = SUPABASE_SERVICE_KEY.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("role") == "service_role"
    except Exception:
        return False


def sincronizar_supabase(df: pd.DataFrame, batch_size: int = 500, max_workers: int = 3):
    if not chave_escrita_valida():
        print("=" * 72)
        print(" [BLOQUEADO] Sincronização Supabase NÃO executada.")
        print(" Motivo: SUPABASE_SERVICE_KEY ausente ou inválida no ficheiro .env")
        print(" A chave anon (pública) é apenas de LEITURA desde a Fase 0 de segurança.")
        print(" Solução: Supabase > Project Settings > API Keys > copiar 'service_role'")
        print("          (ou 'secret key' sb_secret_...) e colar no .env:")
        print("          SUPABASE_SERVICE_KEY=<chave>")
        print(" O CSV local foi gerado normalmente. Depois de configurar, execute:")
        print("          python etl_santiago_supabase.py --apenas-sync")
        print("=" * 72)
        return
    t0 = time.time()
    print(f"  [9/9] A preparar envio de {len(df):,} registos para o Supabase (edec-app -> public.contratos_santiago)...")
    records = preparar_registos_supabase(df)
    total = len(records)
    batches = [records[i : i + batch_size] for i in range(0, total, batch_size)]

    endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/contratos_santiago?on_conflict=cil"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    enviados = 0
    erros = 0

    def enviar_lote(idx_batch, lote):
        for tentativa in range(4):
            try:
                resp = requests.post(endpoint, headers=headers, json=lote, timeout=60)
                if resp.status_code in (200, 201, 204):
                    return len(lote), None
                err_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except Exception as exc:
                err_msg = str(exc)
            time.sleep(1.5 * (tentativa + 1))
        return 0, f"Lote {idx_batch}: {err_msg}"

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(enviar_lote, idx, b): idx for idx, b in enumerate(batches)}
        for count_done, fut in enumerate(as_completed(futures), 1):
            qtd_ok, erro = fut.result()
            enviados += qtd_ok
            if erro:
                erros += 1
                print(f"    [ERRO] {erro}")
            if count_done % 20 == 0 or count_done == len(batches):
                pct = (enviados / total) * 100
                print(f"    -> Progresso Supabase: {enviados:,}/{total:,} ({pct:.1f}%) [{time.time() - t0:.1f}s]")

    print("=" * 72)
    print(f" SINCRONIZAÇÃO SUPABASE CONCLUÍDA EM {time.time() - t0:.2f}s!")
    print(f" Total sincronizado: {enviados:,} / {total:,} registos | Lotes com erro: {erros}")
    print("=" * 72)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ETL Contratos Santiago -> Supabase (edec-app)")
    parser.add_argument("--apenas-local", action="store_true", help="Gera apenas o CSV local sem enviar ao Supabase")
    parser.add_argument("--apenas-sync", action="store_true", help="Sincroniza o santiago_consolidado.csv já gerado com o Supabase")
    parser.add_argument("--batch-size", type=int, default=500, help="Tamanho do lote para Upsert no Supabase")
    parser.add_argument("--workers", type=int, default=3, help="Número de conexões paralelas ao Supabase")
    args = parser.parse_args()

    if args.apenas_sync:
        csv_path = os.path.join(BASE_SANTIAGO, "santiago_consolidado.csv")
        df_final = pd.read_csv(csv_path, sep=";", low_memory=False)
        sincronizar_supabase(df_final, batch_size=args.batch_size, max_workers=args.workers)
    else:
        df_final = executar_transformacao()
        exportar_csv_local(df_final)
        if not args.apenas_local:
            sincronizar_supabase(df_final, batch_size=args.batch_size, max_workers=args.workers)
