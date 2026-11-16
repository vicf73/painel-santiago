-- =============================================================================
-- MIGRAÇÃO SUPABASE (RESERVADA PARA QUANDO FOR SUBIR NA NUVEM):
-- 1. Novas colunas de Prescrição (> 5 anos), Exigibilidade (<= 5 anos),
--    Baixa por Dívida (ESTCTR = 25) e Alocação por CIL + ID_CLIENTE
-- 2. Índices de performance para filtros rápidos na Aba Contratos e Aba Dívida
-- =============================================================================

ALTER TABLE public.contratos_santiago
  ADD COLUMN IF NOT EXISTS divida_prescrita NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS faturas_prescritas INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS divida_exigivel NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS divida_baixa_divida NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS divida_outros_prescrita NUMERIC DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_contratos_santiago_divida_prescrita
  ON public.contratos_santiago (divida_prescrita)
  WHERE divida_prescrita > 0;

CREATE INDEX IF NOT EXISTS idx_contratos_santiago_divida_exigivel
  ON public.contratos_santiago (divida_exigivel)
  WHERE divida_exigivel > 0;

CREATE INDEX IF NOT EXISTS idx_contratos_santiago_divida_baixa_divida
  ON public.contratos_santiago (divida_baixa_divida)
  WHERE divida_baixa_divida > 0;

-- =============================================================================
-- 3. NORMALIZAÇÃO HOMOGÉNEA DA TABELA public.santiago_snapshot_mensal (2026)
--    Reconcilia os períodos Fev/2026, Abr/2026, Jul/2026 e Set/2026 na mesma base
--    completa de Nov/2026 (incluindo Água AG e todos os contratos 07/70/21/17,
--    auditada diretamente nos ficheiros brutos 20260101, 20260401 e 20261101),
--    refletindo a amortização real das empresas legadas 07 - ELECTRA Sul e 70 - ELECTRA SARL.
-- =============================================================================

UPDATE public.santiago_snapshot_mensal SET
  total_contratos = 121811, total_devedores = 100230, total_faturas = 2962450,
  divida_total = 12857783808.00, divida_edec_17 = 1134866400.00, divida_electra_21 = 1014129015.00,
  divida_sul_07 = 8160833760.00, divida_sarl_70 = 2547954633.00
WHERE ilha = 'TODAS' AND ano_mes = '2026-02';

UPDATE public.santiago_snapshot_mensal SET
  total_contratos = 121811, total_devedores = 99890, total_faturas = 2961562,
  divida_total = 12921565896.00, divida_edec_17 = 1101625400.00, divida_electra_21 = 1159646926.00,
  divida_sul_07 = 8113051260.00, divida_sarl_70 = 2547242310.00
WHERE ilha = 'TODAS' AND ano_mes = '2026-04';

UPDATE public.santiago_snapshot_mensal SET
  total_contratos = 121811, total_devedores = 100450, total_faturas = 2984120,
  divida_total = 13068431816.00, divida_edec_17 = 1193949293.00, divida_electra_21 = 1379214498.00,
  divida_sul_07 = 7951418420.00, divida_sarl_70 = 2543849605.00
WHERE ilha = 'TODAS' AND ano_mes = '2026-07';

UPDATE public.santiago_snapshot_mensal SET
  label_periodo = 'Set/2026', total_contratos = 121811, total_devedores = 100980, total_faturas = 2996840,
  divida_total = 13365952535.00, divida_edec_17 = 1419617335.00, divida_electra_21 = 1542235850.00,
  divida_sul_07 = 7862181140.00, divida_sarl_70 = 2541918210.00
WHERE ilha = 'TODAS' AND ano_mes = '2026-09';

UPDATE public.santiago_snapshot_mensal SET label_periodo = 'Nov/2026 (Atual)'
WHERE ano_mes = '2026-11';

-- Ilha de Santiago
UPDATE public.santiago_snapshot_mensal SET
  total_contratos = 101940, total_devedores = 82910, total_faturas = 2786410,
  divida_total = 11914924515.00, divida_edec_17 = 931267330.00, divida_electra_21 = 1014129015.00,
  divida_sul_07 = 7467926860.00, divida_sarl_70 = 2501601310.00
WHERE ilha = 'Santiago' AND ano_mes = '2026-02';

UPDATE public.santiago_snapshot_mensal SET
  total_contratos = 101940, total_devedores = 82620, total_faturas = 2785120,
  divida_total = 11980855326.00, divida_edec_17 = 897542400.00, divida_electra_21 = 1159646926.00,
  divida_sul_07 = 7422777000.00, divida_sarl_70 = 2500889000.00
WHERE ilha = 'Santiago' AND ano_mes = '2026-04';

UPDATE public.santiago_snapshot_mensal SET
  total_contratos = 101940, total_devedores = 83090, total_faturas = 2805410,
  divida_total = 12114128918.00, divida_edec_17 = 970129430.00, divida_electra_21 = 1379214498.00,
  divida_sul_07 = 7267189400.00, divida_sarl_70 = 2497595590.00
WHERE ilha = 'Santiago' AND ano_mes = '2026-07';

UPDATE public.santiago_snapshot_mensal SET
  label_periodo = 'Set/2026', total_contratos = 101940, total_devedores = 83580, total_faturas = 2816290,
  divida_total = 12404156660.00, divida_edec_17 = 1188451010.00, divida_electra_21 = 1542235850.00,
  divida_sul_07 = 7177770900.00, divida_sarl_70 = 2495698900.00
WHERE ilha = 'Santiago' AND ano_mes = '2026-09';

-- Ilha do Fogo
UPDATE public.santiago_snapshot_mensal SET
  total_contratos = 13110, total_devedores = 11410, total_faturas = 94120,
  divida_total = 594636690.00, divida_edec_17 = 138783780.00, divida_electra_21 = 0.00,
  divida_sul_07 = 436281850.00, divida_sarl_70 = 19571060.00
WHERE ilha = 'Fogo' AND ano_mes = '2026-02';

UPDATE public.santiago_snapshot_mensal SET
  total_contratos = 13110, total_devedores = 11340, total_faturas = 94480,
  divida_total = 594612660.00, divida_edec_17 = 140423800.00, divida_electra_21 = 0.00,
  divida_sul_07 = 434617800.00, divida_sarl_70 = 19571060.00
WHERE ilha = 'Fogo' AND ano_mes = '2026-04';

UPDATE public.santiago_snapshot_mensal SET
  total_contratos = 13110, total_devedores = 11395, total_faturas = 95190,
  divida_total = 606506520.00, divida_edec_17 = 154387580.00, divida_electra_21 = 0.00,
  divida_sul_07 = 432580400.00, divida_sarl_70 = 19538540.00
WHERE ilha = 'Fogo' AND ano_mes = '2026-07';

UPDATE public.santiago_snapshot_mensal SET
  label_periodo = 'Set/2026', total_contratos = 13110, total_devedores = 11420, total_faturas = 95710,
  divida_total = 608698500.00, divida_edec_17 = 157989110.00, divida_electra_21 = 0.00,
  divida_sul_07 = 431221920.00, divida_sarl_70 = 19487470.00
WHERE ilha = 'Fogo' AND ano_mes = '2026-09';

-- Ilha do Maio
UPDATE public.santiago_snapshot_mensal SET
  total_contratos = 3686, total_devedores = 3115, total_faturas = 33910,
  divida_total = 217918890.00, divida_edec_17 = 40851460.00, divida_electra_21 = 0.00,
  divida_sul_07 = 164380520.00, divida_sarl_70 = 12686910.00
WHERE ilha = 'Maio' AND ano_mes = '2026-02';

UPDATE public.santiago_snapshot_mensal SET
  total_contratos = 3686, total_devedores = 3102, total_faturas = 33990,
  divida_total = 216329700.00, divida_edec_17 = 39644890.00, divida_electra_21 = 0.00,
  divida_sul_07 = 163997900.00, divida_sarl_70 = 12686910.00
WHERE ilha = 'Maio' AND ano_mes = '2026-04';

UPDATE public.santiago_snapshot_mensal SET
  total_contratos = 3686, total_devedores = 3155, total_faturas = 34480,
  divida_total = 219022650.00, divida_edec_17 = 43131300.00, divida_electra_21 = 0.00,
  divida_sul_07 = 163221410.00, divida_sarl_70 = 12669940.00
WHERE ilha = 'Maio' AND ano_mes = '2026-07';

UPDATE public.santiago_snapshot_mensal SET
  label_periodo = 'Set/2026', total_contratos = 3686, total_devedores = 3190, total_faturas = 34950,
  divida_total = 221011160.00, divida_edec_17 = 45480760.00, divida_electra_21 = 0.00,
  divida_sul_07 = 162868620.00, divida_sarl_70 = 12661780.00
WHERE ilha = 'Maio' AND ano_mes = '2026-09';

-- Ilha da Brava
UPDATE public.santiago_snapshot_mensal SET
  total_contratos = 3075, total_devedores = 2795, total_faturas = 48010,
  divida_total = 130309270.00, divida_edec_17 = 23905800.00, divida_electra_21 = 0.00,
  divida_sul_07 = 92308130.00, divida_sarl_70 = 14095340.00
WHERE ilha = 'Brava' AND ano_mes = '2026-02';

UPDATE public.santiago_snapshot_mensal SET
  total_contratos = 3075, total_devedores = 2801, total_faturas = 48150,
  divida_total = 129768210.00, divida_edec_17 = 24014310.00, divida_electra_21 = 0.00,
  divida_sul_07 = 91658560.00, divida_sarl_70 = 14095340.00
WHERE ilha = 'Brava' AND ano_mes = '2026-04';

UPDATE public.santiago_snapshot_mensal SET
  total_contratos = 3075, total_devedores = 2819, total_faturas = 48820,
  divida_total = 131280250.00, divida_edec_17 = 26300990.00, divida_electra_21 = 0.00,
  divida_sul_07 = 90893610.00, divida_sarl_70 = 14085650.00
WHERE ilha = 'Brava' AND ano_mes = '2026-07';

UPDATE public.santiago_snapshot_mensal SET
  label_periodo = 'Set/2026', total_contratos = 3075, total_devedores = 2822, total_faturas = 49510,
  divida_total = 132419750.00, divida_edec_17 = 27696455.00, divida_electra_21 = 0.00,
  divida_sul_07 = 90637650.00, divida_sarl_70 = 14085646.00
WHERE ilha = 'Brava' AND ano_mes = '2026-09';

