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
from datetime import datetime, timezone
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
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_KEY", "").strip()
ETL_SECRET_TOKEN = os.environ.get("ETL_SECRET_TOKEN", "").strip()
# Segurança (Fase 0): a chave anon (pública) é APENAS de leitura.
# A escrita no Supabase usa SUPABASE_SERVICE_KEY ou ETL_SECRET_TOKEN (guardado apenas no .env local).
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

    # Suporte dual para os 2 formatos de extração da pasta CONTRATO:
    # 1) Formato Resumido (26 colunas - ex: 2Contratos_E017.*.txt)
    usecols_26 = [0, 1, 3, 5, 8, 9, 12, 14, 16, 17, 19, 20, 22]
    names_26 = ["EMP_CTR", "UC", "NIB", "CIL", "ID", "TPCT", "NOME", "LOCALIDADE", "PRODUTO", "TARIFA", "ESTCTR", "DT_INI", "DT_BAIXA"]

    # 2) Formato Completo TCONTRATOS (97 colunas - ex: TContratos_E021, TContratos_SUL_AG, TContratos_SUL_EN)
    usecols_97 = [1, 2, 3, 5, 6, 12, 14, 17, 20, 27, 54]
    names_97 = ["EMP_CTR", "PRODUTO", "UC", "NIB", "CIL", "ESTCTR", "TARIFA", "DT_INI", "DT_BAIXA", "ID", "TPCT"]

    dfs = []
    for f in ficheiros:
        with open(f, "r", encoding="latin1", errors="ignore") as fh:
            primeira_linha = fh.readline()
        n_cols = len(primeira_linha.split("\t"))

        if n_cols <= 35:
            df = pd.read_csv(
                f,
                sep="\t",
                header=None,
                usecols=usecols_26,
                names=names_26,
                encoding="utf-8",
                encoding_errors="replace",
                quoting=3,
                dtype=str,
                on_bad_lines="skip",
            )
        else:
            df = pd.read_csv(
                f,
                sep="\t",
                header=None,
                usecols=usecols_97,
                names=names_97,
                encoding="latin1",
                quoting=3,
                dtype=str,
                on_bad_lines="skip",
            )
            df["NOME"] = None
            df["LOCALIDADE"] = None
            df = df[names_26]
        dfs.append(df)

    df_ctr = pd.concat(dfs, ignore_index=True)

    # Normalização de Empresa e códigos de 5/6 dígitos (600 / 60) para 8 dígitos
    df_ctr["EMP_CTR"] = df_ctr["EMP_CTR"].fillna("").astype(str).str.strip().str.lstrip("0")
    for col in ["CIL", "NIB", "ID"]:
        s = df_ctr[col].fillna("").astype(str).str.strip()
        tam = s.str.len()
        df_ctr[col] = np.where(tam == 5, "600" + s, np.where(tam == 6, "60" + s, s))

    # Tipagem inicial (Int64.Type e type text)
    for col in ["UC", "NIB", "CIL", "ID", "TPCT", "ESTCTR"]:
        df_ctr[col] = pd.to_numeric(df_ctr[col], errors="coerce").astype("Int64")

    for col in ["NOME", "LOCALIDADE", "PRODUTO", "TARIFA", "DT_INI", "DT_BAIXA"]:
        df_ctr[col] = df_ctr[col].fillna("").astype(str).str.strip()
        df_ctr.loc[df_ctr[col].isin(["", "0", "00000000"]), col] = None

    # ComCIL_ID = Text.From([CIL]) & "," & Text.From([ID])
    df_ctr["CIL_ID"] = df_ctr["CIL"].astype(str) + "," + df_ctr["ID"].astype(str)

    # Inclusão dos Contratos Especiais de Água (E021 - Águas de Santiago S.A.)
    df_ads = pd.DataFrame([
        {
            "EMP_CTR": "21",
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
            "DT_INI": "20200101",
            "DT_BAIXA": None,
            "CIL_ID": "60220187,60209538",
        },
        {
            "EMP_CTR": "21",
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
            "DT_INI": "20200101",
            "DT_BAIXA": None,
            "CIL_ID": "60220188,60209538",
        },
    ])
    df_ctr = pd.concat([df_ctr, df_ads], ignore_index=True)

    print(f"  [1/9] CONTRATO (Multi-Empresa 17/21/07/70) carregado: {len(df_ctr):,} linhas ({time.time() - t0:.2f}s)")
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
                usecols=[0, 4, 5, 9, 10, 11, 12, 13, 15, 19, 26],
                names=["EMP_ID", "UNIDADE", "CIL", "CLI_CONTA", "NOME", "TPCT", "TARIFA", "PRODUTO", "DT_EMISSAO", "NUMFACT", "VAL_DIVIDA"],
                encoding="latin1",
                quoting=3,
                dtype=str,
                on_bad_lines="skip",
            )
            dfs.append(df)

        df_div = pd.concat(dfs, ignore_index=True)
        df_div["EMP_ID"] = df_div["EMP_ID"].fillna("").astype(str).str.strip().str.lstrip("0")
        df_div["PRODUTO"] = df_div["PRODUTO"].fillna("").astype(str).str.strip().str.upper()
        df_div["VAL_DIVIDA"] = pd.to_numeric(
            df_div["VAL_DIVIDA"].str.replace(r"[^0-9,.\-]", "", regex=True), errors="coerce"
        ).fillna(0.0)

        bruto_linhas = len(df_div)
        bruto_ecv = float(df_div["VAL_DIVIDA"].sum())

        ucs_excluir = {
            "010000000", "010101000", "010301000", "010400000", "010401000",
            "010501000", "010502000", "010601000", "010602000", "010603000",
            "010201003", "010201004", "010201002", "010201001",
        }
        mask_uc_excl = df_div["UNIDADE"].fillna("").str.strip().isin(ucs_excluir)
        excl_ucs_ecv = float(df_div.loc[mask_uc_excl, "VAL_DIVIDA"].sum())
        df_div = df_div[~mask_uc_excl].copy()

        for col in ["CIL", "CLI_CONTA"]:
            s = df_div[col].fillna("").str.strip()
            tam = s.str.len()
            df_div[col] = np.where(tam == 5, "600" + s, np.where(tam == 6, "60" + s, s))

        # Garantir apenas CILs de 8 dígitos
        mask_cil_ok = df_div["CIL"].str.len() == 8
        excl_cil_ecv = float(df_div.loc[~mask_cil_ok, "VAL_DIVIDA"].sum())
        df_div = df_div[mask_cil_ok].copy()
        df_div["CIL"] = pd.to_numeric(df_div["CIL"], errors="coerce").astype("Int64")
        mask_cil_num = df_div["CIL"].notna()
        excl_cil_ecv += float(df_div.loc[~mask_cil_num, "VAL_DIVIDA"].sum())
        df_div = df_div[mask_cil_num].copy()

        # Identificação dinâmica de prescrição (> N anos a partir da data de execução; padrão 5 anos)
        anos_presc = int(os.environ.get("ANOS_PRESCRICAO", "5"))
        corte_presc_int = int((pd.Timestamp.today().normalize() - pd.DateOffset(years=anos_presc)).strftime("%Y%m%d"))
        dt_emi_num = pd.to_numeric(df_div["DT_EMISSAO"].fillna("").astype(str).str.strip().str[:8], errors="coerce").fillna(0)
        is_presc = (dt_emi_num > 19000101) & (dt_emi_num < corte_presc_int)
        df_div["VAL_PRESC"] = np.where(is_presc, df_div["VAL_DIVIDA"], 0.0)
        df_div["FAT_PRESC"] = np.where(is_presc, 1, 0)

        # Vetorização por Empresa (17: EDEC Sul, 21: Electra SA, 7: Electra Sul, 70: Electra SARL) e Produto AG (Água)
        df_div["VAL_17"] = np.where(df_div["EMP_ID"] == "17", df_div["VAL_DIVIDA"], 0.0)
        df_div["FAT_17"] = np.where(df_div["EMP_ID"] == "17", 1, 0)
        df_div["VAL_21"] = np.where(df_div["EMP_ID"] == "21", df_div["VAL_DIVIDA"], 0.0)
        df_div["FAT_21"] = np.where(df_div["EMP_ID"] == "21", 1, 0)
        df_div["VAL_7"]  = np.where(df_div["EMP_ID"] == "7",  df_div["VAL_DIVIDA"], 0.0)
        df_div["FAT_7"]  = np.where(df_div["EMP_ID"] == "7",  1, 0)
        df_div["VAL_70"] = np.where(df_div["EMP_ID"] == "70", df_div["VAL_DIVIDA"], 0.0)
        df_div["FAT_70"] = np.where(df_div["EMP_ID"] == "70", 1, 0)
        df_div["VAL_AG"] = np.where(df_div["PRODUTO"] == "AG", df_div["VAL_DIVIDA"], 0.0)
        df_div["FAT_AG"] = np.where(df_div["PRODUTO"] == "AG", 1, 0)

        dim_divida = df_div.groupby("CIL", dropna=False, as_index=False, sort=False).agg(
            VALOR=("VAL_DIVIDA", "sum"),
            QTD=("NUMFACT", "count"),
            divida_prescrita=("VAL_PRESC", "sum"),
            faturas_prescritas=("FAT_PRESC", "sum"),
            divida_edec=("VAL_17", "sum"),
            faturas_edec=("FAT_17", "sum"),
            divida_electra=("VAL_21", "sum"),
            faturas_electra=("FAT_21", "sum"),
            divida_sul=("VAL_7", "sum"),
            faturas_sul=("FAT_7", "sum"),
            divida_sarl=("VAL_70", "sum"),
            faturas_sarl=("FAT_70", "sum"),
            divida_ag=("VAL_AG", "sum"),
            faturas_ag=("FAT_AG", "sum"),
            UC_DIV=("UNIDADE", "first"),
            ID_DIV=("CLI_CONTA", "first"),
            NOME_DIV=("NOME", "first"),
            TPCT_DIV=("TPCT", "first"),
            TARIFA_DIV=("TARIFA", "first"),
            PRODUTO_DIV=("PRODUTO", "first"),
        )
        dim_divida["divida_exigivel"] = (dim_divida["VALOR"] - dim_divida["divida_prescrita"]).round(2)

        conds = [
            (dim_divida["divida_edec"] >= dim_divida["divida_electra"]) & (dim_divida["divida_edec"] >= dim_divida["divida_sul"]) & (dim_divida["divida_edec"] >= dim_divida["divida_sarl"]) & (dim_divida["divida_edec"] > 0),
            (dim_divida["divida_electra"] >= dim_divida["divida_edec"]) & (dim_divida["divida_electra"] >= dim_divida["divida_sul"]) & (dim_divida["divida_electra"] >= dim_divida["divida_sarl"]) & (dim_divida["divida_electra"] > 0),
            (dim_divida["divida_sul"] >= dim_divida["divida_edec"]) & (dim_divida["divida_sul"] >= dim_divida["divida_electra"]) & (dim_divida["divida_sul"] >= dim_divida["divida_sarl"]) & (dim_divida["divida_sul"] > 0),
            (dim_divida["divida_sarl"] > 0),
        ]
        choices = ["EDEC Sul", "Electra SA", "Electra Sul", "Electra SARL"]
        dim_divida["empresa_predom"] = np.select(conds, choices, default="Sem Dívida")
        dim_divida.attrs["funil_divida"] = {
            "bruto_linhas": int(bruto_linhas),
            "bruto_ecv": round(bruto_ecv, 2),
            "excl_ucs_ecv": round(excl_ucs_ecv, 2),
            "excl_cil_ecv": round(excl_cil_ecv, 2),
            "pos_filtros_ecv": round(float(dim_divida["VALOR"].sum()), 2),
            "corte_prescricao": str(corte_presc_int),
            "anos_prescricao": anos_presc,
        }

        # Agregação por (CIL, CLI_CONTA) e por (CIL, CLI_CONTA, EMP_ID) para rastreio de Dívida por Titular/Contrato (CIL + ID)
        df_div["ID_CONTA"] = pd.to_numeric(df_div["CLI_CONTA"], errors="coerce").astype("Int64")
        div_por_cil_id = (
            df_div[df_div["ID_CONTA"].notna()]
            .groupby(["CIL", "ID_CONTA"], as_index=False, sort=False)
            .agg(
                VAL_CONTA=("VAL_DIVIDA", "sum"),
                FAT_CONTA=("NUMFACT", "count"),
                VAL_PRESC_CONTA=("VAL_PRESC", "sum"),
                FAT_PRESC_CONTA=("FAT_PRESC", "sum"),
                NOME_CONTA=("NOME", "first"),
                EMP_CONTA=("EMP_ID", "first"),
                PROD_CONTA=("PRODUTO", "first"),
            )
        )
        div_por_cil_id_emp = (
            df_div[df_div["ID_CONTA"].notna()]
            .groupby(["CIL", "ID_CONTA", "EMP_ID"], as_index=False, sort=False)
            .agg(
                VAL_CONTA=("VAL_DIVIDA", "sum"),
                FAT_CONTA=("NUMFACT", "count"),
                VAL_PRESC_CONTA=("VAL_PRESC", "sum"),
                FAT_PRESC_CONTA=("FAT_PRESC", "sum"),
                NOME_CONTA=("NOME", "first"),
                PROD_CONTA=("PRODUTO", "first"),
            )
        )
        dim_divida.attrs["div_por_cil_id"] = div_por_cil_id
        dim_divida.attrs["div_por_cil_id_emp"] = div_por_cil_id_emp

        print(
            f"  [2/9] Dim_DIVIDA processada direto de Atual_script/DIVIDA: {len(dim_divida):,} CILs únicos "
            f"[Total: {dim_divida['VALOR'].sum():,.2f} ECV | Prescrita (>5a): {dim_divida['divida_prescrita'].sum():,.0f} ECV | "
            f"Água (AG): {dim_divida['divida_ag'].sum():,.0f} ECV | "
            f"EDEC(17): {dim_divida['divida_edec'].sum():,.0f} | ELECTRA(21): {dim_divida['divida_electra'].sum():,.0f} | "
            f"Sul(07): {dim_divida['divida_sul'].sum():,.0f} | SARL(70): {dim_divida['divida_sarl'].sum():,.0f}] ({time.time() - t0:.2f}s)"
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


def carregar_dim_faturacao_direta(dim_uc: pd.DataFrame | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """
    Ingestão DIRETA de alta performance a partir de Atual_script/FATURAÇAO/*.txt
    (E017 EDEC Sul + E021 Electra SA AdS), eliminando a dependência de Fat_piv.xlsx.

    Regras Blindadas:
    1. Lê estritamente colunas 0..22 (suporta ficheiros de 23, 24 e 27 colunas).
    2. Forward-fill das colunas 0..19 quando um conceito seguinte vem partido em linha curta (<23 cols).
    3. Filtra UCs da Região Sul (Santiago, Fogo, Maio, Brava).
    4. Evita dupla contagem: Valor Total é contabilizado 1x por fatura; kWh usa X30 (fallback X20).
    5. Calcula T3 (últimos 3 meses disponíveis), Variação_% vs 3 meses anteriores e Alerta_Desvio ('Desv_Fat').
    """
    import re
    from collections import defaultdict

    t0 = time.time()
    pasta_fat = os.path.join(BASE_ATUAL_SCRIPT, "FATURAÇAO")
    ficheiros = []
    if os.path.isdir(pasta_fat):
        ficheiros = sorted([
            os.path.join(pasta_fat, f)
            for f in os.listdir(pasta_fat)
            if not f.startswith("~$") and not f.startswith(".") and f.lower().endswith(".txt")
        ])

    if not ficheiros:
        p_fat = localizar_ficheiro_mais_recente(BASE_SANTIAGO, ("Fat_piv", "Faturacao", "Faturaçao"), "Fat_piv.xlsx")
        df_fat = pd.read_excel(p_fat, sheet_name="FATURAÇAO", usecols=["CIL", "T3", "Alerta_Desvio", "Variação_%"])
        df_fat["CIL"] = pd.to_numeric(df_fat["CIL"], errors="coerce").astype("Int64")
        df_fat["T3"] = pd.to_numeric(df_fat["T3"], errors="coerce")
        df_fat["Variação_%"] = pd.to_numeric(df_fat["Variação_%"], errors="coerce")
        df_fat = df_fat.drop_duplicates(subset=["CIL"], keep="first").rename(
            columns={"T3": "FATURAÇAO.T3", "Alerta_Desvio": "FATURAÇAO.Alerta_Desvio", "Variação_%": "FATURAÇAO.Variação_%"}
        )
        return df_fat, []

    ilhas_sul = {"Santiago", "Fogo", "Maio", "Brava"}
    if dim_uc is not None and len(dim_uc) > 0:
        ucs_sul = {
            str(int(c)).zfill(9)
            for c, ilha in zip(dim_uc["COD_UNI"], dim_uc["ILHA"])
            if pd.notna(c) and ilha in ilhas_sul
        }
    else:
        ucs_sul = {"010201000"}

    # Acumuladores por lote mensal (YYYYMM extraído do nome do ficheiro)
    kwh_cil_mes = defaultdict(lambda: defaultdict(float))  # emp17: cil -> {ym: kwh}
    resumo_mensal = []

    for fp in ficheiros:
        nome_arq = os.path.basename(fp)
        m_ym = re.search(r"\.(\d{6})\d{2}\.txt$", nome_arq)
        ym = m_ym.group(1) if m_ym else "000000"

        faturas_vistas = set()
        fat_val_tot = defaultdict(float)   # (emp, prd) -> sum(VAL_TOT)
        fat_qtd_count = defaultdict(int)   # (emp, prd) -> count faturas
        fat_x30 = {}                       # (emp, numfat) -> (cil_int, prd, qtd)
        fat_x20 = {}                       # (emp, numfat) -> (cil_int, prd, qtd)
        linhas_partidas_recup = 0

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
                    conc = parts[20].strip()
                    qtd_s = parts[21].strip()
                elif n_p >= 3 and last_prefix is not None and last_in_sul:
                    # Linha partida (conceito adicional da mesma fatura)
                    linhas_partidas_recup += 1
                    parts = last_prefix + parts[:3]
                    conc = parts[20].strip()
                    qtd_s = parts[21].strip()
                else:
                    continue

                emp = parts[0].strip().lstrip("0")
                prd = parts[2].strip().upper()
                numfat = parts[15].strip()
                if not numfat:
                    continue

                key_fat = (emp, numfat)
                if key_fat not in faturas_vistas:
                    faturas_vistas.add(key_fat)
                    try:
                        val_t = float(parts[18].strip())
                    except ValueError:
                        val_t = 0.0
                    fat_val_tot[(emp, prd)] += val_t
                    fat_qtd_count[(emp, prd)] += 1

                if conc in ("X30", "X20"):
                    cil_s = parts[4].strip()
                    tam = len(cil_s)
                    if tam == 5:
                        cil_s = "600" + cil_s
                    elif tam == 6:
                        cil_s = "60" + cil_s
                    if len(cil_s) == 8 and cil_s.isdigit():
                        try:
                            qtd_v = float(qtd_s)
                        except ValueError:
                            qtd_v = 0.0
                        cil_int = int(cil_s)
                        if conc == "X30":
                            fat_x30[key_fat] = (cil_int, prd, fat_x30.get(key_fat, (cil_int, prd, 0.0))[2] + qtd_v)
                        else:
                            fat_x20[key_fat] = (cil_int, prd, fat_x20.get(key_fat, (cil_int, prd, 0.0))[2] + qtd_v)

        # Consolidar consumo (X30 prioritário; fallback X20)
        kwh_por_emp_prd = defaultdict(float)
        todas_chaves_cons = set(fat_x30.keys()) | set(fat_x20.keys())
        for k_fat in todas_chaves_cons:
            emp = k_fat[0]
            cil_int, prd, qtd_v = fat_x30.get(k_fat) or fat_x20[k_fat]
            kwh_por_emp_prd[(emp, prd)] += qtd_v
            if emp == "17":
                kwh_cil_mes[cil_int][ym] += qtd_v

        for (emp, prd), val_ecv in sorted(fat_val_tot.items()):
            kwh_tot = kwh_por_emp_prd.get((emp, prd), 0.0)
            pm = (val_ecv / kwh_tot) if kwh_tot > 0 else 0.0
            resumo_mensal.append({
                "lote_ym": ym,
                "empresa": emp,
                "produto": prd,
                "faturas": fat_qtd_count[(emp, prd)],
                "consumo_qtd": round(kwh_tot, 2),
                "valor_faturado_ecv": round(val_ecv, 2),
                "preco_medio_ecv": round(pm, 2),
                "linhas_partidas_recuperadas": linhas_partidas_recup,
            })

    # Determinar janela T_atual (últimos 3 lotes de E017) e T_prev (3 lotes imediatamente anteriores)
    yms_17 = sorted({r["lote_ym"] for r in resumo_mensal if r["empresa"] == "17"})
    yms_atual = yms_17[-3:] if len(yms_17) >= 3 else yms_17
    yms_prev = yms_17[-6:-3] if len(yms_17) >= 6 else yms_17[: max(0, len(yms_17) - len(yms_atual))]

    registros_fat = []
    for cil_int, mapa_mes in kwh_cil_mes.items():
        t_atual = sum(mapa_mes.get(m, 0.0) for m in yms_atual)
        t_prev = sum(mapa_mes.get(m, 0.0) for m in yms_prev)
        var_pct = ((t_atual - t_prev) / t_prev) if t_prev > 0 else np.nan
        alerta = "Desv_Fat" if (t_atual <= 0 or (pd.notna(var_pct) and var_pct < -0.30)) else None
        registros_fat.append({
            "CIL": cil_int,
            "FATURAÇAO.T3": round(t_atual, 2),
            "FATURAÇAO.Alerta_Desvio": alerta,
            "FATURAÇAO.Variação_%": round(var_pct, 6) if pd.notna(var_pct) else np.nan,
        })

    df_fat = pd.DataFrame(registros_fat)
    df_fat["CIL"] = pd.to_numeric(df_fat["CIL"], errors="coerce").astype("Int64")

    # Salvar resumo mensal para auditoria e consultas
    out_res = os.path.join(BASE_SANTIAGO, "faturacao_resumo_mensal.json")
    try:
        with open(out_res, "w", encoding="utf-8") as fj:
            json.dump({
                "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "janela_t_atual": yms_atual,
                "janela_t_prev": yms_prev,
                "mensal": resumo_mensal,
            }, fj, ensure_ascii=False, indent=2)
    except Exception:
        pass

    tot_17_ecv = sum(r["valor_faturado_ecv"] for r in resumo_mensal if r["empresa"] == "17")
    tot_17_kwh = sum(r["consumo_qtd"] for r in resumo_mensal if r["empresa"] == "17")
    tot_21_ecv = sum(r["valor_faturado_ecv"] for r in resumo_mensal if r["empresa"] == "21")
    pm_17 = (tot_17_ecv / tot_17_kwh) if tot_17_kwh > 0 else 0.0
    print(
        f"        - Faturação (Direto TXT): {len(df_fat):,} CILs | T_atual={yms_atual} vs T_prev={yms_prev} | "
        f"E017={tot_17_ecv/1e9:.2f}B ECV ({tot_17_kwh/1e6:.1f} GWh, PM={pm_17:.2f} ECV/kWh) | "
        f"E021 AdS={tot_21_ecv/1e6:.1f}M ECV ({time.time() - t0:.2f}s)"
    )
    return df_fat, resumo_mensal


def carregar_dimensoes_santiago(dim_uc: pd.DataFrame | None = None):
    t0 = time.time()
    # Dim_Anomalia
    p_anom = localizar_ficheiro_mais_recente(BASE_SANTIAGO, ("Anomalia",), "Anomalia de Leitura Setembro 2026.xlsx")
    df_anom = pd.read_excel(p_anom, sheet_name=0, usecols=["CIL", "Anomalia"])
    df_anom["CIL"] = pd.to_numeric(df_anom["CIL"], errors="coerce").astype("Int64")
    df_anom = df_anom.drop_duplicates(subset=["CIL"], keep="first").rename(columns={"Anomalia": "Anomalia.1"})

    # Dim_Faturacao (Direto de Atual_script/FATURAÇAO/*.txt com fallback Fat_piv.xlsx)
    df_fat, _ = carregar_dim_faturacao_direta(dim_uc)

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
        f"        - Faturação: {len(df_fat):,} reg. (T3 + Desv_Fat)\n"
        f"        - GEO / PT : {os.path.basename(p_geo)} ({len(df_geo):,} reg.)\n"
        f"        - IMTT     : {os.path.basename(p_imtt)} ({len(df_imtt):,} reg.)"
    )
    return df_anom, df_fat, df_geo, df_imtt


def carregar_dim_itinerario() -> pd.DataFrame:
    """
    Carrega itenrar.csv da pasta Atual_script (ou santiago) e extrai:
    - SEQ: Sequência do cliente no itinerário / rota
    - ITINERARIO: Código do itinerário / rota de leitura
    Normaliza o CIL para o padrão Santiago (8 dígitos: 60XXXXXX), tratando prefixo regional.
    """
    t0 = time.time()
    caminho = os.path.join(BASE_ATUAL_SCRIPT, "itenrar.csv")
    if not os.path.exists(caminho):
        caminho = os.path.join(BASE_SANTIAGO, "itenrar.csv")

    if not os.path.exists(caminho):
        print("  [AVISO] itenrar.csv não encontrado. Dimensão de itinerários não carregada.")
        return pd.DataFrame(columns=["CIL", "ITINERARIO", "SEQ"])

    df_it = pd.read_csv(caminho, sep=";", encoding="latin1")
    s_cil = pd.to_numeric(df_it["CIL"], errors="coerce").dropna().astype("int64")
    df_it = df_it.loc[s_cil.index].copy()

    def _norm_cil(v: int) -> int:
        return int(f"60{v:06d}") if v < 60000000 else v

    df_it["CIL"] = [_norm_cil(x) for x in df_it["CIL"].astype("int64")]
    df_it["CIL"] = df_it["CIL"].astype("Int64")
    df_it["SEQ"] = pd.to_numeric(df_it["SEQ"], errors="coerce").astype("Int64")
    col_itin = next((c for c in df_it.columns if "ITIN" in c.upper()), None)
    if col_itin:
        df_it["ITINERARIO"] = pd.to_numeric(df_it[col_itin], errors="coerce").astype("Int64")
    else:
        df_it["ITINERARIO"] = pd.NA

    df_it = df_it[["CIL", "ITINERARIO", "SEQ"]].drop_duplicates(subset=["CIL"], keep="first")
    print(
        f"  [4.1/9] Dimensão Itinerário/Rotas carregada ({time.time() - t0:.2f}s):\n"
        f"        - Ficheiro  : {os.path.basename(caminho)} ({len(df_it):,} CILs mapeados com SEQ e ITINERARIO)"
    )
    return df_it


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
        cob_por_emp = {"17": 0.0, "21": 0.0, "7": 0.0, "70": 0.0}
        for fp in ficheiros:
            if os.path.getsize(fp) == 0:
                continue
            nome_fp = os.path.basename(fp).upper()
            if "E021" in nome_fp:
                emp_fp = "21"
            elif "SARL" in nome_fp or "E070" in nome_fp:
                emp_fp = "70"
            elif "SUL" in nome_fp or "E007" in nome_fp:
                emp_fp = "7"
            else:
                emp_fp = "17"

            df = pd.read_csv(
                fp, sep="\t", header=None, usecols=[0, 1, 8, 11, 16, 21],
                names=["UC", "CIL", "DATA_COBR", "VALOR", "TIPO_DOC", "data_fat"],
                dtype=str, quoting=3, encoding="latin1", on_bad_lines="skip"
            )
            if len(df) == 0:
                continue
            uc = df["UC"].fillna("").str.strip()
            df["UC"] = np.where(uc == "", "00", uc.str.zfill(9))
            cil = df["CIL"].fillna("").str.strip()
            tam_cil = cil.str.len()
            cil = np.where(tam_cil == 5, "600" + cil, np.where(tam_cil == 6, "60" + cil, cil))
            cil_s = pd.Series(cil, index=df.index)
            tipo = df["TIPO_DOC"].fillna("").str.strip().str.upper()
            
            # Filtro defensivo: UC de Santiago, não XX, CIL de 8 dígitos estritos (após normalização 5/6 -> 8)
            mask = (
                (df["UC"] != "00")
                & (~df["UC"].isin(ucs_excluir))
                & (tipo != "XX")
                & (cil_s.str.len() == 8)
                & cil_s.str.isdigit()
            )
            df = df[mask].copy()
            df["CIL"] = cil_s[mask]
            
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
            df["ano_num"] = dc.dt.year.fillna(0).astype("int32")
            df["mes_num"] = dc.dt.month.fillna(0).astype("int32")
            df["CIL"] = pd.to_numeric(df["CIL"], errors="coerce").astype("Int64")
            df = df[df["CIL"].notna() & (df["ano_num"] >= 2026) & (df["mes_num"] > 0)]
            cob_por_emp[emp_fp] = cob_por_emp.get(emp_fp, 0.0) + float(df["VALOR"].sum())
            
            # Pré-agrupamento por ficheiro mantendo (ano_num, mes_num) para não misturar anos
            dfs.append(df.groupby(["CIL", "ano_num", "mes_num", "mat_str"], as_index=False, sort=False)["VALOR"].sum())
        
        df_all = pd.concat(dfs, ignore_index=True)
        df_all = df_all.groupby(["CIL", "ano_num", "mes_num", "mat_str"], as_index=False, sort=False)["VALOR"].sum()
        print(
            f"        -> Cobrança por Empresa 2026: 17-EDEC Sul={cob_por_emp['17']/1e6:,.1f}M | "
            f"21-Electra SA={cob_por_emp['21']/1e6:,.1f}M | 07-Sul={cob_por_emp['7']/1e6:,.1f}M | "
            f"70-SARL={cob_por_emp['70']/1e6:,.1f}M ECV"
        )

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

    # 2. Meses com soma líquida positiva (ordenado por ano_num*100 + mes_num)
    if "ano_num" not in df_all.columns:
        df_all["ano_num"] = 2026
    df_all["ym_num"] = df_all["ano_num"] * 100 + df_all["mes_num"]
    df_mes = df_all.groupby(["CIL", "ym_num", "mes_num"], as_index=False, sort=False)["VALOR"].sum()
    df_mes_pos = df_mes[df_mes["VALOR"] > 0]
    df_mes_agg = df_mes_pos.groupby("CIL", as_index=False, sort=False).agg(
        cob_qtd_meses=("ym_num", "nunique"),
        max_ym_num=("ym_num", "max"),
    )
    df_mes_agg["cob_ultimo_mes"] = (df_mes_agg["max_ym_num"] % 100).map(inv_mes)

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

    from etl.manifesto import gerar_e_validar_manifesto
    gerar_e_validar_manifesto(BASE_SANTIAGO, BASE_ATUAL_SCRIPT)

    df_ctr = carregar_contratos()
    dim_tpct, dim_estctr, dim_uc = carregar_dimensoes_codigos()
    dim_divida = carregar_dim_divida()
    dim_aparelho = carregar_dim_aparelho()
    dim_anomalia, dim_faturacao, dim_geo, dim_imtt = carregar_dimensoes_santiago(dim_uc)
    dim_itinerario = carregar_dim_itinerario()
    dim_cf1 = carregar_dim_cf1_autos()
    dim_cob = carregar_dim_cobranca()

    # 4. CRUZAMENTO COM UC, ORDENAÇÃO DE TITULAR ATUAL E HISTÓRICO MULTI-CONTRATO POR CIL
    t0 = time.time()
    div_por_cil_id = dim_divida.attrs.get("div_por_cil_id", pd.DataFrame())

    # Incorporar CILs presentes em DIVIDA (ex: clientes de Água AG ou contas históricas) que não estão em CONTRATO
    if "UC_DIV" in dim_divida.columns:
        cils_existentes = set(df_ctr["CIL"].dropna())
        div_orf = dim_divida[~dim_divida["CIL"].isin(cils_existentes)].copy()
        if len(div_orf) > 0:
            uc_num = pd.to_numeric(div_orf["UC_DIV"].fillna("").astype(str).str.strip(), errors="coerce").astype("Int64")
            id_num = pd.to_numeric(div_orf["ID_DIV"].fillna("").astype(str).str.strip(), errors="coerce").astype("Int64")
            tpct_num = pd.to_numeric(div_orf["TPCT_DIV"].fillna("").astype(str).str.strip(), errors="coerce").astype("Int64")
            prod_s = div_orf["PRODUTO_DIV"].fillna("AG").astype(str).str.strip()
            df_extra = pd.DataFrame({
                "EMP_CTR": np.where(prod_s == "AG", "21", "17"),
                "UC": uc_num,
                "NIB": id_num,
                "CIL": div_orf["CIL"],
                "ID": id_num,
                "TPCT": tpct_num,
                "NOME": div_orf["NOME_DIV"].fillna("CLIENTE EXTRAÇÃO DÍVIDA").astype(str).str.strip(),
                "LOCALIDADE": np.where(prod_s == "AG", "REDE ÁGUA (EXTRAÇÃO DÍVIDA AG)", "EXTRAÇÃO DÍVIDA HISTÓRICA"),
                "PRODUTO": prod_s,
                "TARIFA": div_orf["TARIFA_DIV"].fillna("A1").astype(str).str.strip(),
                "ESTCTR": pd.Series(30, index=div_orf.index, dtype="Int64"),
                "DT_INI": None,
                "DT_BAIXA": None,
                "CIL_ID": div_orf["CIL"].astype(str) + "," + id_num.astype(str),
            })
            df_ctr = pd.concat([df_ctr, df_extra], ignore_index=True)
            print(f"  [3.5/9] Incorporados {len(df_extra):,} CILs exclusivos da pasta DIVIDA (Água AG / Histórico)")

    df_ctr = df_ctr.merge(dim_uc, left_on="UC", right_on="COD_UNI", how="left")
    ilhas_edec = {"Santiago", "Fogo", "Maio", "Brava"}
    df_ctr = df_ctr[df_ctr["ILHA"].isin(ilhas_edec)].copy()

    # Enriquecer NOME (via E017 + DIVIDA) e LOCALIDADE (por CIL) para os contratos de 97 colunas (TContratos_*)
    mapa_nome = {}
    if len(div_por_cil_id) > 0:
        sub_n_div = div_por_cil_id[div_por_cil_id["NOME_CONTA"].notna() & (div_por_cil_id["NOME_CONTA"].str.strip() != "")]
        mapa_nome.update(dict(zip(sub_n_div["ID_CONTA"], sub_n_div["NOME_CONTA"].str.strip())))
    sub_n_ctr = df_ctr[df_ctr["NOME"].notna() & (df_ctr["NOME"] != "")]
    mapa_nome.update(dict(zip(sub_n_ctr["ID"], sub_n_ctr["NOME"])))

    mask_sem_nome = df_ctr["NOME"].isna() | (df_ctr["NOME"] == "")
    df_ctr.loc[mask_sem_nome, "NOME"] = df_ctr.loc[mask_sem_nome, "ID"].map(mapa_nome)
    mask_ainda_sem_nome = df_ctr["NOME"].isna() | (df_ctr["NOME"] == "")
    df_ctr.loc[mask_ainda_sem_nome, "NOME"] = "CLIENTE ID " + df_ctr.loc[mask_ainda_sem_nome, "ID"].astype(str)

    sub_loc = df_ctr[df_ctr["LOCALIDADE"].notna() & (df_ctr["LOCALIDADE"] != "")]
    mapa_loc = dict(zip(sub_loc["CIL"], sub_loc["LOCALIDADE"]))
    mask_sem_loc = df_ctr["LOCALIDADE"].isna() | (df_ctr["LOCALIDADE"] == "")
    df_ctr.loc[mask_sem_loc, "LOCALIDADE"] = df_ctr.loc[mask_sem_loc, "CIL"].map(mapa_loc)
    mask_ainda_sem_loc = df_ctr["LOCALIDADE"].isna() | (df_ctr["LOCALIDADE"] == "")
    df_ctr.loc[mask_ainda_sem_loc, "LOCALIDADE"] = df_ctr.loc[mask_ainda_sem_loc, "DESC_UNI"]

    # Ordenar contratos por prioridade para eleger o Titular Atual de cada CIL:
    # 1º Hierarquia de Empresa (17 EDEC SA é a referência principal -> 21 ELECTRA SA AdS -> 7 ELECTRA Sul -> 70 ELECTRA SARL)
    # 2º Contrato em Vigor / Ativo (ESTCTR 12, 13, 14, 15, 10, 11) vs Baixado/Rescindido (21, 25, 27, 28)
    # 3º Data de Início mais recente (DT_INI descendente)
    df_ctr["_prio_emp"] = df_ctr["EMP_CTR"].map({"17": 1, "21": 2, "7": 3, "70": 4}).fillna(5)
    df_ctr["_prio_ativo"] = np.where(df_ctr["ESTCTR"].isin([12, 13, 14, 15, 10, 11]), 0, 1)
    df_ctr["_dt_ini_ord"] = -pd.to_numeric(df_ctr["DT_INI"], errors="coerce").fillna(0)
    df_ctr = df_ctr.sort_values(
        by=["CIL", "_prio_emp", "_prio_ativo", "_dt_ini_ord"],
        ascending=[True, True, True, True],
        kind="mergesort",
    )

    # Mapear pares (CIL, ID) que possuem contrato em Baixa por Dívida (ESTCTR = 25)
    pares_baixa_div = set(
        df_ctr[df_ctr["ESTCTR"] == 25][["CIL", "ID"]].dropna().itertuples(index=False, name=None)
    )

    # Construir Histórico de Contratos e Titulares por CIL (1 CIL -> N Contratos / Clientes via CIL + ID)
    div_por_cil_id_emp = dim_divida.attrs.get("div_por_cil_id_emp", pd.DataFrame())
    df_ctr_est = df_ctr.merge(dim_estctr, left_on="ESTCTR", right_on="Código", how="left")
    if len(div_por_cil_id_emp) > 0:
        df_ctr_est["_is_first_emp"] = ~df_ctr_est.duplicated(subset=["CIL", "ID", "EMP_CTR"], keep="first")
        df_ctr_est = df_ctr_est.merge(
            div_por_cil_id_emp[["CIL", "ID_CONTA", "EMP_ID", "VAL_CONTA", "FAT_CONTA", "VAL_PRESC_CONTA", "FAT_PRESC_CONTA"]],
            left_on=["CIL", "ID", "EMP_CTR"],
            right_on=["CIL", "ID_CONTA", "EMP_ID"],
            how="left",
        )
        df_ctr_est["VAL_CONTA"] = np.where(df_ctr_est["_is_first_emp"], df_ctr_est["VAL_CONTA"].fillna(0.0), 0.0)
        df_ctr_est["FAT_CONTA"] = np.where(df_ctr_est["_is_first_emp"], df_ctr_est["FAT_CONTA"].fillna(0), 0).astype("int64")
        df_ctr_est["VAL_PRESC_CONTA"] = np.where(df_ctr_est["_is_first_emp"], df_ctr_est["VAL_PRESC_CONTA"].fillna(0.0), 0.0)
        df_ctr_est["FAT_PRESC_CONTA"] = np.where(df_ctr_est["_is_first_emp"], df_ctr_est["FAT_PRESC_CONTA"].fillna(0), 0).astype("int64")

        # Adicionar ao histórico eventuais contas de dívida (CIL, ID_CONTA, EMP_ID) cujo contrato antigo não conste nos TXT de CONTRATO
        triplas_ctr = set(zip(df_ctr_est["CIL"], df_ctr_est["ID"], df_ctr_est["EMP_CTR"]))
        cils_edec_set = set(df_ctr_est["CIL"].dropna())
        div_extra_hist = div_por_cil_id_emp[
            div_por_cil_id_emp["CIL"].isin(cils_edec_set)
            & (~pd.Series(list(zip(div_por_cil_id_emp["CIL"], div_por_cil_id_emp["ID_CONTA"], div_por_cil_id_emp["EMP_ID"])), index=div_por_cil_id_emp.index).isin(triplas_ctr))
        ].copy()
        cols_hist = ["CIL", "EMP_CTR", "ID", "NOME", "PRODUTO", "Descrição", "DT_INI", "DT_BAIXA", "VAL_CONTA", "FAT_CONTA", "VAL_PRESC_CONTA", "FAT_PRESC_CONTA"]
        if len(div_extra_hist) > 0:
            df_hist_extra = pd.DataFrame({
                "CIL": div_extra_hist["CIL"],
                "EMP_CTR": div_extra_hist["EMP_ID"],
                "ID": div_extra_hist["ID_CONTA"],
                "NOME": div_extra_hist["NOME_CONTA"].fillna("CONTA HISTÓRICA DÍVIDA"),
                "PRODUTO": div_extra_hist["PROD_CONTA"].fillna("BT"),
                "Descrição": "Conta Histórica c/ Dívida",
                "DT_INI": None,
                "DT_BAIXA": None,
                "VAL_CONTA": div_extra_hist["VAL_CONTA"].fillna(0.0),
                "FAT_CONTA": div_extra_hist["FAT_CONTA"].fillna(0).astype("int64"),
                "VAL_PRESC_CONTA": div_extra_hist["VAL_PRESC_CONTA"].fillna(0.0),
                "FAT_PRESC_CONTA": div_extra_hist["FAT_PRESC_CONTA"].fillna(0).astype("int64"),
            })
            df_hist_all = pd.concat([
                df_ctr_est[cols_hist],
                df_hist_extra,
            ], ignore_index=True)
        else:
            df_hist_all = df_ctr_est[cols_hist]
    else:
        df_ctr_est["VAL_CONTA"] = 0.0
        df_ctr_est["FAT_CONTA"] = 0
        df_ctr_est["VAL_PRESC_CONTA"] = 0.0
        df_ctr_est["FAT_PRESC_CONTA"] = 0
        df_hist_all = df_ctr_est[["CIL", "EMP_CTR", "ID", "NOME", "PRODUTO", "Descrição", "DT_INI", "DT_BAIXA", "VAL_CONTA", "FAT_CONTA", "VAL_PRESC_CONTA", "FAT_PRESC_CONTA"]]

    from collections import defaultdict
    hist_map = defaultdict(list)
    clientes_set_map = defaultdict(set)
    for cil_v, emp_v, id_v, nome_v, prod_v, est_v, dini_v, dbai_v, val_v, fat_v, vpresc_v, fpresc_v in zip(
        df_hist_all["CIL"].tolist(),
        df_hist_all["EMP_CTR"].tolist(),
        df_hist_all["ID"].tolist(),
        df_hist_all["NOME"].tolist(),
        df_hist_all["PRODUTO"].tolist(),
        df_hist_all["Descrição"].tolist(),
        df_hist_all["DT_INI"].tolist(),
        df_hist_all["DT_BAIXA"].tolist(),
        df_hist_all["VAL_CONTA"].tolist(),
        df_hist_all["FAT_CONTA"].tolist(),
        df_hist_all["VAL_PRESC_CONTA"].tolist(),
        df_hist_all["FAT_PRESC_CONTA"].tolist(),
    ):
        if pd.isna(cil_v):
            continue
        cil_int = int(cil_v)
        id_int = int(id_v) if pd.notna(id_v) else None
        if id_int is not None:
            clientes_set_map[cil_int].add(id_int)
        est_str = str(est_v or "")
        is_baixa_d = ((cil_int, id_int) in pares_baixa_div) or ("Baixa por D" in est_str)
        hist_map[cil_int].append({
            "emp": str(emp_v or ""),
            "id": id_int,
            "nome": str(nome_v or ""),
            "prod": str(prod_v or ""),
            "est": est_str,
            "dt_ini": str(dini_v) if pd.notna(dini_v) and dini_v else None,
            "dt_baixa": str(dbai_v) if pd.notna(dbai_v) and dbai_v else None,
            "divida": round(float(val_v or 0.0), 2),
            "faturas": int(fat_v or 0),
            "divida_prescrita": round(float(vpresc_v or 0.0), 2),
            "faturas_prescritas": int(fpresc_v or 0),
            "baixa_divida": bool(is_baixa_d),
        })

    tot_linhas_ctr_edec = len(df_ctr)
    if not manter_duplicados_cil:
        df = df_ctr.drop_duplicates(subset=["CIL"], keep="first").copy()
    else:
        df = df_ctr.copy()

    print(
        f"  [4/9] Universo EDEC filtrado (Santiago, Fogo, Maio, Brava): {tot_linhas_ctr_edec:,} contratos totais -> "
        f"{len(df):,} locais de consumo (CILs únicos) ({time.time() - t0:.2f}s)"
    )

    # 5. ENRIQUECIMENTO DE DADOS (JOINS DEFENSIVOS 1:1 POR CIL)
    df = df.merge(dim_tpct, left_on="TPCT", right_on="COD_CLI", how="left")
    df = df.merge(dim_estctr, left_on="ESTCTR", right_on="Código", how="left").rename(columns={"Descrição": "EST_CTR"})
    cols_div_join = [
        c for c in [
            "CIL", "VALOR", "QTD", "divida_prescrita", "faturas_prescritas", "divida_exigivel",
            "divida_edec", "faturas_edec", "divida_electra", "faturas_electra",
            "divida_sul", "faturas_sul", "divida_sarl", "faturas_sarl",
            "divida_ag", "faturas_ag", "empresa_predom",
        ] if c in dim_divida.columns
    ]
    df = df.merge(dim_divida[cols_div_join], on="CIL", how="left")
    for c_emp in ["divida_edec", "divida_electra", "divida_sul", "divida_sarl", "divida_ag", "divida_prescrita", "divida_exigivel"]:
        if c_emp in df.columns:
            df[c_emp] = pd.to_numeric(df[c_emp], errors="coerce").fillna(0.0)
    for c_fat in ["faturas_edec", "faturas_electra", "faturas_sul", "faturas_sarl", "faturas_ag", "faturas_prescritas"]:
        if c_fat in df.columns:
            df[c_fat] = pd.to_numeric(df[c_fat], errors="coerce").fillna(0).astype("int64")
    if "empresa_predom" in df.columns:
        df["empresa_predom"] = df["empresa_predom"].fillna("Sem Dívida")

    # Cálculo de Dívida e Faturas do Titular Atual vs Outros Titulares (por CIL + ID) e Dívida em Baixa por Dívida
    if len(div_por_cil_id) > 0:
        df = df.merge(
            div_por_cil_id[["CIL", "ID_CONTA", "VAL_CONTA", "FAT_CONTA", "VAL_PRESC_CONTA"]].rename(
                columns={"VAL_CONTA": "_val_tit_atual", "FAT_CONTA": "_fat_tit_atual", "VAL_PRESC_CONTA": "_presc_tit_atual"}
            ),
            left_on=["CIL", "ID"],
            right_on=["CIL", "ID_CONTA"],
            how="left",
        )
        val_tot_cil = pd.to_numeric(df["VALOR"], errors="coerce").fillna(0.0)
        qtd_tot_cil = pd.to_numeric(df["QTD"], errors="coerce").fillna(0).astype("int64")
        presc_tot_cil = pd.to_numeric(df["divida_prescrita"], errors="coerce").fillna(0.0)
        df["divida_titular_atual"] = np.minimum(val_tot_cil, pd.to_numeric(df["_val_tit_atual"], errors="coerce").fillna(0.0)).round(2)
        df["faturas_titular_atual"] = np.minimum(qtd_tot_cil, pd.to_numeric(df["_fat_tit_atual"], errors="coerce").fillna(0).astype("int64"))
        df["divida_outros_titulares"] = np.maximum(0.0, val_tot_cil - df["divida_titular_atual"]).round(2)
        presc_tit = np.minimum(presc_tot_cil, pd.to_numeric(df["_presc_tit_atual"], errors="coerce").fillna(0.0))
        df["divida_outros_prescrita"] = np.maximum(0.0, presc_tot_cil - presc_tit).round(2)

        # Somar dívida em Baixa por Dívida (ESTCTR = 25) por CIL (incluindo titular atual ou ex-titulares)
        mask_bd = [((c, i) in pares_baixa_div) for c, i in zip(div_por_cil_id["CIL"], div_por_cil_id["ID_CONTA"])]
        div_bd_por_cil = (
            div_por_cil_id[mask_bd]
            .groupby("CIL", as_index=False)["VAL_CONTA"]
            .sum()
            .rename(columns={"VAL_CONTA": "divida_baixa_divida"})
        )
        df = df.merge(div_bd_por_cil, on="CIL", how="left")
        df["divida_baixa_divida"] = pd.to_numeric(df["divida_baixa_divida"], errors="coerce").fillna(0.0).round(2)
    else:
        df["divida_titular_atual"] = pd.to_numeric(df["VALOR"], errors="coerce").fillna(0.0).round(2)
        df["faturas_titular_atual"] = pd.to_numeric(df["QTD"], errors="coerce").fillna(0).astype("int64")
        df["divida_outros_titulares"] = 0.0
        df["divida_outros_prescrita"] = 0.0
        df["divida_baixa_divida"] = 0.0

    # Isolamento explícito do CIL técnico 99999999 (468 clientes sem CIL definido)
    mask_cil_99 = df["CIL"] == 99999999
    if mask_cil_99.any():
        df.loc[mask_cil_99, "NOME"] = "CONTA TÉCNICA S/ CIL DEFINIDO (468 CLIENTES)"
        df.loc[mask_cil_99, "EST_CTR"] = "Conta Técnica Isolada (CIL 99999999)"
        df.loc[mask_cil_99, "GRUP_TP_CLI"] = "Conta Técnica Isolada"
        df.loc[mask_cil_99, "LOCALIDADE"] = "SEM LOCAL DE CONSUMO DEFINIDO"

    cils_lista = df["CIL"].tolist()
    df["qtd_contratos_hist"] = [max(1, len(hist_map.get(int(c), []))) if pd.notna(c) else 1 for c in cils_lista]
    df["qtd_clientes_distintos"] = [max(1, len(clientes_set_map.get(int(c), set()))) if pd.notna(c) else 1 for c in cils_lista]
    df["historico_contratos"] = [
        json.dumps(hist_map.get(int(c), []), ensure_ascii=False) if pd.notna(c) else "[]"
        for c in cils_lista
    ]

    df = df.merge(dim_aparelho, on="CIL", how="left")
    df = df.merge(dim_anomalia, on="CIL", how="left")
    df = df.merge(dim_faturacao, on="CIL", how="left")
    df = df.merge(dim_geo, on="CIL", how="left")
    df = df.merge(dim_imtt, on="CIL", how="left")
    df = df.merge(dim_itinerario, on="CIL", how="left")
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
        "VALOR", "QTD", "divida_prescrita", "faturas_prescritas", "divida_exigivel",
        "DA_INST", "DATA_LEITURA", "MODELO", "CONTADOR", "LEITURA",
        "Mat_Contador", "Mat_Leitura", "tp_fat",
        "Anomalia.1", "FATURAÇAO.T3", "FATURAÇAO.Alerta_Desvio", "FATURAÇAO.Variação_%", "Med_Fat",
        "lat", "long", "PT", "TIP", "ITINERARIO", "SEQ",
        "cf1_qtd_autos", "cf1_kwh_total", "cf1_val_total", "cf1_val_divida",
        "cf1_ultimo_ano", "cf1_estado_divida", "cf1_estado_juridico", "cf1_evidencia_fotos",
        "cob_valor_total", "cob_qtd_meses", "cob_ultimo_mes", "cob_maturidade_predom",
        "cob_valor_atraso", "status_cobranca",
        "divida_edec", "faturas_edec", "divida_electra", "faturas_electra", "divida_sul", "faturas_sul", "divida_sarl", "faturas_sarl", "divida_ag", "faturas_ag", "empresa_predom",
        "qtd_contratos_hist", "qtd_clientes_distintos", "divida_titular_atual", "faturas_titular_atual", "divida_outros_titulares", "divida_outros_prescrita", "divida_baixa_divida", "historico_contratos",
        "Score_Risco", "Nivel_Risco", "Motivo_Risco", "Criterio",
    ]
    df = df[colunas_finais].copy()
    if "funil_divida" in dim_divida.attrs:
        df.attrs["funil_divida"] = dict(dim_divida.attrs["funil_divida"])

    crit_cnt = (df["Nivel_Risco"] == "CRÍTICO").sum()
    alto_cnt = (df["Nivel_Risco"] == "ALTO").sum()
    cf1_cnt = (df["cf1_qtd_autos"] > 0).sum()
    sem_pag_cnt = (df["status_cobranca"] == "Devedor Sem Pagamento 2026").sum()
    multi_cli_cnt = (df["qtd_clientes_distintos"] > 1).sum()
    div_outros_tot = df["divida_outros_titulares"].sum()
    div_presc_tot = df["divida_prescrita"].sum()
    div_bd_tot = df["divida_baixa_divida"].sum()
    print(
        f"  [7/9] Joins e Score de Risco concluídos: {len(df):,} locais de consumo (CILs)\n"
        f"        -> Risco Crítico: {crit_cnt:,} | Alto: {alto_cnt:,}\n"
        f"        -> Dívida Prescrita (>5 anos): {div_presc_tot:,.0f} ECV | Baixa p/ Dívida: {div_bd_tot:,.0f} ECV\n"
        f"        -> CILs Multi-Cliente: {multi_cli_cnt:,} | Dívida Outros Titulares (CIL+ID): {div_outros_tot:,.0f} ECV\n"
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
    try:
        df.to_csv(out_csv, sep=";", index=False, encoding="utf-8-sig")
    except PermissionError:
        out_alt = os.path.join(BASE_SANTIAGO, f"santiago_consolidado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        print(
            f"\n  [AVISO] O ficheiro '{out_csv}' está aberto no Excel ou bloqueado por outro programa!\n"
            f"          -> Feche o ficheiro no Excel para permitir sobrescrevê-lo.\n"
            f"          -> A gravar cópia alternativa em: {out_alt}"
        )
        df.to_csv(out_alt, sep=";", index=False, encoding="utf-8-sig")
        out_csv = out_alt

    # Etapa 2: Guardar cópia histórica mensal comprimida em backups/santiago_AAAAMM.csv.gz
    pasta_bkp = os.path.join(BASE_SANTIAGO, "backups")
    os.makedirs(pasta_bkp, exist_ok=True)
    tag_mes = datetime.now().strftime("%Y%m")
    out_gz = os.path.join(pasta_bkp, f"santiago_{tag_mes}.csv.gz")
    try:
        df.to_csv(out_gz, sep=";", index=False, encoding="utf-8-sig", compression="gzip")
    except PermissionError:
        pass
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
        "divida_ag": pd.to_numeric(df["divida_ag"], errors="coerce").fillna(0.0) if "divida_ag" in df.columns else 0.0,
        "faturas_ag": pd.to_numeric(df["faturas_ag"], errors="coerce").fillna(0).astype("Int64") if "faturas_ag" in df.columns else 0,
        "empresa_predom": df["empresa_predom"] if "empresa_predom" in df.columns else None,
        "qtd_contratos_hist": pd.to_numeric(df["qtd_contratos_hist"], errors="coerce").fillna(1).astype("Int64") if "qtd_contratos_hist" in df.columns else 1,
        "qtd_clientes_distintos": pd.to_numeric(df["qtd_clientes_distintos"], errors="coerce").fillna(1).astype("Int64") if "qtd_clientes_distintos" in df.columns else 1,
        "divida_titular_atual": pd.to_numeric(df["divida_titular_atual"], errors="coerce").fillna(0.0) if "divida_titular_atual" in df.columns else 0.0,
        "faturas_titular_atual": pd.to_numeric(df["faturas_titular_atual"], errors="coerce").fillna(0).astype("Int64") if "faturas_titular_atual" in df.columns else 0,
        "divida_outros_titulares": pd.to_numeric(df["divida_outros_titulares"], errors="coerce").fillna(0.0) if "divida_outros_titulares" in df.columns else 0.0,
        "divida_prescrita": pd.to_numeric(df["divida_prescrita"], errors="coerce").fillna(0.0) if "divida_prescrita" in df.columns else 0.0,
        "faturas_prescritas": pd.to_numeric(df["faturas_prescritas"], errors="coerce").fillna(0).astype("Int64") if "faturas_prescritas" in df.columns else 0,
        "divida_exigivel": pd.to_numeric(df["divida_exigivel"], errors="coerce").fillna(0.0) if "divida_exigivel" in df.columns else 0.0,
        "divida_outros_prescrita": pd.to_numeric(df["divida_outros_prescrita"], errors="coerce").fillna(0.0) if "divida_outros_prescrita" in df.columns else 0.0,
        "divida_baixa_divida": pd.to_numeric(df["divida_baixa_divida"], errors="coerce").fillna(0.0) if "divida_baixa_divida" in df.columns else 0.0,
        "historico_contratos": [
            (json.loads(x) if isinstance(x, str) and x.startswith("[") else (x if isinstance(x, list) else []))
            for x in (df["historico_contratos"].tolist() if "historico_contratos" in df.columns else [[] for _ in range(len(df))])
        ],
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
        "ultima_carga_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ativo_extracao": True,
    })
    # Remover linhas sem CIL
    df_db = df_db[df_db["cil"].notna()].copy()
    # Converter para JSON e recarregar substitui qualquer NaN/NA por None nativo em C!
    return json.loads(df_db.to_json(orient="records"))


def chave_escrita_valida() -> bool:
    """Confirma que existe SUPABASE_SERVICE_KEY ou ETL_SECRET_TOKEN válido no .env."""
    if ETL_SECRET_TOKEN and len(ETL_SECRET_TOKEN) >= 24:
        return True
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


def validar_e_reconciliar_etl(df: pd.DataFrame) -> dict:
    """
    Etapa 3: Valida integridade e reconcilia a soma das dívidas por empresa (17, 21, 07, 70)
    contra a dívida total consolidada antes de permitir a carga.
    """
    tot_contratos = len(df)
    por_ilha = df["ILHA"].value_counts().to_dict() if "ILHA" in df.columns else {}
    div_total = float(pd.to_numeric(df["VALOR"], errors="coerce").fillna(0.0).sum())
    div_17 = float(pd.to_numeric(df.get("divida_edec", 0), errors="coerce").fillna(0.0).sum())
    div_21 = float(pd.to_numeric(df.get("divida_electra", 0), errors="coerce").fillna(0.0).sum())
    div_07 = float(pd.to_numeric(df.get("divida_sul", 0), errors="coerce").fillna(0.0).sum())
    div_70 = float(pd.to_numeric(df.get("divida_sarl", 0), errors="coerce").fillna(0.0).sum())
    soma_empresas = div_17 + div_21 + div_07 + div_70
    dif_abs = abs(div_total - soma_empresas)
    dif_pct = (dif_abs / div_total * 100.0) if div_total > 0 else 0.0
    reconciliado = (tot_contratos >= 50000) and (dif_pct <= 0.5)

    resumo = {
        "executado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_contratos": int(tot_contratos),
        "contratos_santiago": int(por_ilha.get("Santiago", 0)),
        "contratos_fogo": int(por_ilha.get("Fogo", 0)),
        "contratos_maio": int(por_ilha.get("Maio", 0)),
        "contratos_brava": int(por_ilha.get("Brava", 0)),
        "divida_total": round(div_total, 2),
        "divida_edec_17": round(div_17, 2),
        "divida_electra_21": round(div_21, 2),
        "divida_sul_07": round(div_07, 2),
        "divida_sarl_70": round(div_70, 2),
        "reconciliacao_ok": bool(reconciliado),
        "diferenca_reconciliacao_pct": round(dif_pct, 4),
    }

    funil = df.attrs.get("funil_divida", {})
    if funil:
        bruto_ecv = float(funil.get("bruto_ecv", 0.0))
        excl_ucs = float(funil.get("excl_ucs_ecv", 0.0))
        excl_cil = float(funil.get("excl_cil_ecv", 0.0))
        pos_filt = float(funil.get("pos_filtros_ecv", 0.0))
        fora_univ = max(0.0, pos_filt - div_total)
        print(f"  [8.5/9] Reconciliação de Auditoria & Funil de Origem -> Destino (Etapa 3):")
        print(f"          -> Bruto TXT ({funil.get('bruto_linhas', 0):,} linhas): {bruto_ecv:,.2f} ECV")
        print(f"             (-) UCs fora Região Sul : {excl_ucs:,.2f} ECV")
        print(f"             (-) CILs inválidos        : {excl_cil:,.2f} ECV")
        print(f"             (-) Fora universo Sul     : {fora_univ:,.2f} ECV")
        print(f"          -> Carregado Região Sul ({tot_contratos:,} CILs): {div_total:,.2f} ECV")
        print(f"          -> Soma Empresas (17+21+07+70): {soma_empresas:,.2f} ECV (Dif: {dif_pct:.4f}%) | Prescrição < {funil.get('corte_prescricao', '-')}")
        print(f"          -> Status Reconciliação: {'APROVADO ✔' if reconciliado else 'FALHOU ✖'}")
    else:
        print(f"  [8.5/9] Reconciliação de Auditoria (Etapa 3):")
        print(f"          -> Contratos: {tot_contratos:,} | Dívida Total: {div_total:,.2f} ECV")
        print(f"          -> Soma Empresas (17+21+07+70): {soma_empresas:,.2f} ECV (Dif: {dif_pct:.4f}%)")
        print(f"          -> Status Reconciliação: {'APROVADO ✔' if reconciliado else 'FALHOU ✖'}")
    return resumo


def sincronizar_supabase(df: pd.DataFrame, batch_size: int = 500, max_workers: int = 3):
    resumo_auditoria = validar_e_reconciliar_etl(df)
    if not resumo_auditoria["reconciliacao_ok"]:
        raise RuntimeError(
            f"Carga abortada pela Reconciliação (Etapa 3): Diferença={resumo_auditoria['diferenca_reconciliacao_pct']}% "
            f"ou total de contratos inválido ({resumo_auditoria['total_contratos']})."
        )
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
    ts_inicio_carga = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"  [9/9] A preparar envio de {len(df):,} registos para o Supabase (edec-app -> public.contratos_santiago)...")
    records = preparar_registos_supabase(df)
    total = len(records)
    batches = [records[i : i + batch_size] for i in range(0, total, batch_size)]

    usar_rpc_token = bool(ETL_SECRET_TOKEN and not SUPABASE_SERVICE_KEY)
    api_key_auth = SUPABASE_SERVICE_KEY if not usar_rpc_token else SUPABASE_ANON_KEY
    endpoint = (
        f"{SUPABASE_URL.rstrip('/')}/rest/v1/rpc/etl_upsert_lote_santiago"
        if usar_rpc_token
        else f"{SUPABASE_URL.rstrip('/')}/rest/v1/contratos_santiago?on_conflict=cil"
    )
    headers = {
        "apikey": api_key_auth,
        "Authorization": f"Bearer {api_key_auth}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    enviados = 0
    erros = 0

    def enviar_lote(idx_batch, lote):
        payload_envio = {"p_etl_token": ETL_SECRET_TOKEN, "p_lote": lote} if usar_rpc_token else lote
        for tentativa in range(4):
            try:
                resp = requests.post(endpoint, headers=headers, json=payload_envio, timeout=120)
                if resp.status_code in (200, 201, 204):
                    return len(lote), None
                err_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except Exception as exc:
                err_msg = str(exc)
            time.sleep(2.0 * (tentativa + 1))
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

    duracao = round(time.time() - t0, 2)
    # Etapa 3, 4 e 6: Registar execução oficial, atualizar snapshot mensal e pós-carga (inativos + cache KPIs)
    try:
        log_payload = {
            **resumo_auditoria,
            "duracao_segundos": duracao,
            "erros_lotes": erros,
            "observacoes": f"Sincronizados {enviados:,}/{total:,} registos via ETL Python (incluindo Água AG)",
        }
        ano_mes_atual = datetime.now().strftime("%Y-%m")
        label_atual = f"{datetime.now().strftime('%b/%Y').capitalize()} (Atual)"
        snaps = []
        for escopo in ["TODAS", "Santiago", "Fogo", "Maio", "Brava"]:
            sub = df if escopo == "TODAS" else df[df["ILHA"] == escopo]
            val_s = pd.to_numeric(sub["VALOR"], errors="coerce").fillna(0.0)
            qtd_s = pd.to_numeric(sub["QTD"], errors="coerce").fillna(0.0)
            d17 = pd.to_numeric(sub.get("divida_edec", 0), errors="coerce").fillna(0.0)
            f17 = pd.to_numeric(sub.get("faturas_edec", 0), errors="coerce").fillna(0.0)
            d21 = pd.to_numeric(sub.get("divida_electra", 0), errors="coerce").fillna(0.0)
            f21 = pd.to_numeric(sub.get("faturas_electra", 0), errors="coerce").fillna(0.0)
            d07 = pd.to_numeric(sub.get("divida_sul", 0), errors="coerce").fillna(0.0)
            f07 = pd.to_numeric(sub.get("faturas_sul", 0), errors="coerce").fillna(0.0)
            d70 = pd.to_numeric(sub.get("divida_sarl", 0), errors="coerce").fillna(0.0)
            f70 = pd.to_numeric(sub.get("faturas_sarl", 0), errors="coerce").fillna(0.0)
            cob_s = pd.to_numeric(sub.get("cob_valor_total", 0), errors="coerce").fillna(0.0)
            snaps.append({
                "ano_mes": ano_mes_atual,
                "label_periodo": label_atual,
                "ilha": escopo,
                "total_contratos": int(len(sub)),
                "total_devedores": int((val_s > 0).sum()),
                "total_faturas": int(qtd_s.sum()),
                "divida_total": round(float(val_s.sum()), 2),
                "divida_edec_17": round(float(d17.sum()), 2),
                "devedores_edec_17": int((d17 > 0).sum()),
                "faturas_edec_17": int(f17.sum()),
                "divida_electra_21": round(float(d21.sum()), 2),
                "devedores_electra_21": int((d21 > 0).sum()),
                "faturas_electra_21": int(f21.sum()),
                "divida_sul_07": round(float(d07.sum()), 2),
                "devedores_sul_07": int((d07 > 0).sum()),
                "faturas_sul_07": int(f07.sum()),
                "divida_sarl_70": round(float(d70.sum()), 2),
                "devedores_sarl_70": int((d70 > 0).sum()),
                "faturas_sarl_70": int(f70.sum()),
                "cob_total_2026": round(float(cob_s.sum()), 2),
            })

        if usar_rpc_token:
            resp_pos = requests.post(
                f"{SUPABASE_URL.rstrip('/')}/rest/v1/rpc/etl_finalizar_carga_santiago",
                headers={**headers, "Prefer": "return=representation"},
                json={
                    "p_etl_token": ETL_SECRET_TOKEN,
                    "p_inicio_carga": ts_inicio_carga if erros == 0 else None,
                    "p_auditoria": log_payload,
                    "p_snapshots": snaps,
                },
                timeout=300,
            )
            if resp_pos.ok:
                print(f"    -> Pós-Carga & Cache KPIs (Etapa 6): {resp_pos.text}")
            else:
                print(f"    [AVISO] Pós-Carga retornou HTTP {resp_pos.status_code}: {resp_pos.text[:200]}")
        else:
            requests.post(
                f"{SUPABASE_URL.rstrip('/')}/rest/v1/santiago_etl_execucoes",
                headers=headers,
                json=log_payload,
                timeout=20,
            )
            requests.post(
                f"{SUPABASE_URL.rstrip('/')}/rest/v1/santiago_snapshot_mensal?on_conflict=ano_mes,ilha",
                headers=headers,
                json=snaps,
                timeout=20,
            )
            resp_pos = requests.post(
                f"{SUPABASE_URL.rstrip('/')}/rest/v1/rpc/pos_carga_santiago",
                headers={**headers, "Prefer": "return=representation"},
                json={"p_inicio_carga": ts_inicio_carga if erros == 0 else None},
                timeout=60,
            )
            if resp_pos.ok:
                print(f"    -> Pós-Carga (Etapa 6): {resp_pos.text}")
    except Exception as exc_log:
        print(f"    [AVISO] Não foi possível gravar log/snapshot/pós-carga: {exc_log}")

    print("=" * 72)
    print(f" SINCRONIZAÇÃO SUPABASE CONCLUÍDA EM {duracao:.2f}s!")
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
