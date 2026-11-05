/**
 * Configuração Centralizada Partilhada — Projeto EDEC Região Sul (Santiago, Fogo, Maio, Brava)
 * Carregado por painel_santiago.html e apresentacao_edec_administracao.html
 * Nota de Segurança: Contém apenas a chave pública (anon). O acesso aos dados exige
 * autenticação ativa via Supabase Auth (JWT) validada por políticas RLS no PostgreSQL.
 */
window.SANTIAGO_CONFIG = {
  SUPABASE_URL: "https://esbbohmkgbcrpegqvagk.supabase.co",
  SUPABASE_ANON_KEY: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVzYmJvaG1rZ2JjcnBlZ3F2YWdrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM1MDQ3OTUsImV4cCI6MjA5OTA4MDc5NX0.85Ypz7LghhQ37Ur5YE2eLM4PFkMw2o3S8QtbhRSzBuU",
  AUTH_STORAGE_KEY: "santiago_auth_session",
  THEME_STORAGE_KEY: "santiago_theme",
  VERSAO_SISTEMA: "2026.11-RBAC",
  EMPRESAS_CREDORAS: [
    { codigo: "17", sigla: "EDEC SA",      cor: "#60A5FA", descricao: "Faturação Corrente / Pós-Cisão" },
    { codigo: "21", sigla: "ELECTRA SA",   cor: "#FBBF24", descricao: "Contrato Especial AdS" },
    { codigo: "7",  sigla: "EDEC Sul",     cor: "#A78BFA", descricao: "Dívida Sul Histórica" },
    { codigo: "70", sigla: "ELECTRA SARL", cor: "#F472B6", descricao: "Dívida Antiga Legada" }
  ]
};
