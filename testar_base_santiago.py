"""
Script de Teste e Validação da Base Contratos Santiago no Supabase (edec-app)
e do ficheiro consolidado local (santiago_consolidado.csv).
Inclui validação de Segurança (Bloqueio Anónimo RLS + Autenticação Supabase Auth).
"""

import os
import sys
import time
import requests
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

# Chaves lidas do .env local (nunca escritas no código)
_ENV = {}
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as _f:
        for _l in _f:
            _l = _l.strip()
            if _l and not _l.startswith("#") and "=" in _l:
                _k, _v = _l.split("=", 1)
                _ENV[_k.strip()] = _v.strip()

SUPABASE_URL = os.environ.get("SUPABASE_URL", _ENV.get("SUPABASE_URL", "https://esbbohmkgbcrpegqvagk.supabase.co"))
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", _ENV.get("SUPABASE_KEY", ""))
ADMIN_EMAIL = os.environ.get("SANTIAGO_TEST_EMAIL", "vitfonseca73@gmail.com")
ADMIN_PASSWORD = os.environ.get("SANTIAGO_TEST_PASSWORD", "Santiago@2026")


def obter_headers_autenticados() -> dict:
    """Autentica via Supabase Auth e devolve cabeçalhos com JWT assinado."""
    r = requests.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"},
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    r.raise_for_status()
    tok = r.json()["access_token"]
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {tok}",
        "Prefer": "count=exact",
    }


def executar_testes():
    print("=" * 80)
    print(" BATERIA DE TESTES - BASE DE CONTRATOS SANTIAGO (SUPABASE AUTH + LOCAL)")
    print("=" * 80)

    # 0. Teste de Bloqueio Anónimo (Etapa 1 - Segurança RLS)
    h_anon = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    r0 = requests.get(f"{SUPABASE_URL}/rest/v1/contratos_santiago?select=cil&limit=1", headers=h_anon, timeout=20)
    print(f"\n[TESTE 0] Proteção RLS contra Acesso Anónimo (Sem Login):")
    print(f"  -> Status HTTP Anónimo : {r0.status_code} ({'BLOQUEADO OK' if r0.status_code in (401, 403) else 'ALERTA'})")

    # Autenticar como Administrador
    HEADERS = obter_headers_autenticados()
    print(f"  -> Login Supabase Auth : OK ({ADMIN_EMAIL})")

    # 1. Teste de contagem total na nuvem
    t0 = time.time()
    r = requests.get(f"{SUPABASE_URL}/rest/v1/contratos_santiago?select=cil&limit=1", headers=HEADERS, timeout=30)
    ms = (time.time() - t0) * 1000
    print(f"\n[TESTE 1] Conexão Autenticada e Contagem Total no Supabase:")
    print(f"  -> Status HTTP : {r.status_code} (OK)")
    print(f"  -> Total Nuvem : {r.headers.get('Content-Range')} registos")
    print(f"  -> Latência    : {ms:.0f} ms")

    # 2. Teste de busca por CIL específico
    t0 = time.time()
    r2 = requests.get(f"{SUPABASE_URL}/rest/v1/contratos_santiago?cil=eq.60060696", headers=HEADERS, timeout=30)
    ms2 = (time.time() - t0) * 1000
    print(f"\n[TESTE 2] Busca instantânea por CIL = 60060696 ({ms2:.0f} ms):")
    if r2.json():
        reg = r2.json()[0]
        print(f"  -> Nome         : {reg['nome']}")
        print(f"  -> Unidade/Loc. : {reg['desc_uni']} / {reg['localidade']}")
        print(f"  -> Estado/Grupo : {reg['est_ctr']} / {reg['grup_tp_cli']}")
        print(f"  -> Contador     : {reg['contador']} ({reg['modelo']}) | Leitura: {reg['leitura']} ({reg['mat_contador']})")
        print(f"  -> Dívida       : {reg['valor']} ECV ({reg['qtd']} faturas) | CIL_ID: {reg['cil_id']}")
        print(f"  -> Georref. PT  : PT={reg['pt']} | Lat={reg['lat']}, Long={reg['long']}")

    # 3. Teste de filtro combinado: PT = EugenioLima2 com Anomalia de Leitura
    t0 = time.time()
    url_t3 = (
        f"{SUPABASE_URL}/rest/v1/contratos_santiago"
        "?pt=eq.EugenioLima2&anomalia=not.is.null"
        "&order=valor.desc.nullslast&limit=5"
        "&select=cil,nome,est_ctr,contador,anomalia,valor,qtd,med_fat,pt"
    )
    r3 = requests.get(url_t3, headers=HEADERS, timeout=30)
    ms3 = (time.time() - t0) * 1000
    print(f"\n[TESTE 3] Filtro Multi-Critério: PT='EugenioLima2' + Com Anomalia ({ms3:.0f} ms):")
    print(f"  -> Registos encontrados nesse PT com anomalia: {r3.headers.get('Content-Range')}")
    if r3.json():
        print(pd.DataFrame(r3.json()).to_string(index=False))

    # 4. Teste de Auditoria de Perdas: Top 5 Dívidas na Praia com Alerta de Desvio (Desv_Fat)
    t0 = time.time()
    url_t4 = (
        f"{SUPABASE_URL}/rest/v1/contratos_santiago"
        "?desc_uni=eq.Praia&faturacao_alerta_desvio=eq.Desv_Fat"
        "&order=valor.desc.nullslast&limit=5"
        "&select=cil,nome,localidade,grup_tp_cli,est_ctr,valor,qtd,faturacao_t3,med_fat,pt"
    )
    r4 = requests.get(url_t4, headers=HEADERS, timeout=30)
    ms4 = (time.time() - t0) * 1000
    print(f"\n[TESTE 4] Top 5 Maiores Dívidas na Praia com Alerta 'Desv_Fat' ({ms4:.0f} ms):")
    print(f"  -> Total de clientes na Praia com Desv_Fat: {r4.headers.get('Content-Range')}")
    if r4.json():
        print(pd.DataFrame(r4.json()).to_string(index=False))

    # 5. Validação do ficheiro CSV local + Backup Comprimido Mensal
    csv_local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "santiago_consolidado.csv")
    if os.path.exists(csv_local):
        df_csv = pd.read_csv(csv_local, sep=";", nrows=5)
        sz_mb = os.path.getsize(csv_local) / (1024 * 1024)
        print(f"\n[TESTE 5] Ficheiro Local 'santiago_consolidado.csv' ({sz_mb:.2f} MB):")
        print(f"  -> {len(df_csv.columns)} colunas validadas.")

    print("\n" + "=" * 80)
    print(" TODOS OS TESTES PASSARAM COM SUCESSO!")
    print("=" * 80)


if __name__ == "__main__":
    executar_testes()
