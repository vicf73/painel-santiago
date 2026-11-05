let
    // 1. Carregamento e Expansão dos Ficheiros (apenas .txt visíveis)
    Origem = Folder.Files("C:\Users\VICTOR FERREIRA\Desktop\Atual_script\cob_26"),
    #"Ficheiros Ocultos Filtrados1" = Table.SelectRows(Origem, each [Attributes]?[Hidden]? <> true and Text.Lower([Extension]) = ".txt"),
    #"Invocar Função Personalizada1" = Table.AddColumn(#"Ficheiros Ocultos Filtrados1", "Transformar Ficheiro", each #"Transformar Ficheiro"([Content])),
    #"Outras Colunas Removidas1" = Table.SelectColumns(#"Invocar Função Personalizada1", {"Transformar Ficheiro"}),
    #"Coluna de Tabela Expandida1" = Table.ExpandTableColumn(#"Outras Colunas Removidas1", "Transformar Ficheiro", Table.ColumnNames(#"Transformar Ficheiro"(#"Ficheiro de Exemplo"))),

    // 2. Seleção e Renomeação Direta das Colunas Relevantes
    //    (NOVO) Column17 = Tipo de documento (EB/EE/EM = fatura | XX = lançamento de caixa VCI/Pré-pago)
    #"Colunas Selecionadas" = Table.SelectColumns(#"Coluna de Tabela Expandida1", {"Column1", "Column2", "Column9", "Column12", "Column17", "Column22"}),
    #"Colunas Renomeadas" = Table.RenameColumns(#"Colunas Selecionadas", {
        {"Column1", "UC"},
        {"Column2", "cil_"},
        {"Column9", "DATA_COBR"},
        {"Column12", "ECV_raw"},
        {"Column17", "TIPO_DOC"},
        {"Column22", "data_fat"}
    }),

    // 3. Conversão Segura de Datas
    #"Tipo Data Alterado" = Table.TransformColumnTypes(#"Colunas Renomeadas", {
        {"DATA_COBR", type date},
        {"data_fat", type date}
    }),
    #"Erros Data Substituídos" = Table.ReplaceErrorValues(#"Tipo Data Alterado", {{"DATA_COBR", null}, {"data_fat", null}}),

    // 4. TRATAMENTO SEGURO DO VALOR (ECV) - Previne erro DataFormat
    #"Limpeza Texto ECV" = Table.TransformColumns(#"Erros Data Substituídos", {
        {"ECV_raw", each if _ = null then "0" else Text.Select(Text.From(_), {"0".."9", ",", ".", "-"}), type text}
    }),
    #"Tipo ECV Alterado" = Table.TransformColumnTypes(#"Limpeza Texto ECV", {{"ECV_raw", type number}}, "en-US"),
    #"Erros ECV Substituídos" = Table.ReplaceErrorValues(#"Tipo ECV Alterado", {{"ECV_raw", 0}}),
    #"ECV Renomeado" = Table.RenameColumns(#"Erros ECV Substituídos", {{"ECV_raw", "ECV"}}),

    // 5. Cálculo do Intervalo em Dias e Coluna MATURIDADE_
    #"Dias Cobranca Inseridos" = Table.AddColumn(#"ECV Renomeado", "MAT_COBR_DIAS", each
        if [DATA_COBR] <> null and [data_fat] <> null then Duration.Days([DATA_COBR] - [data_fat]) else null, Int64.Type
    ),

    #"MATURIDADE_ Adicionada" = Table.AddColumn(#"Dias Cobranca Inseridos", "MATURIDADE_", each
        if [MAT_COBR_DIAS] = null then "Sem Data"
        else if [MAT_COBR_DIAS] < 31 then "1 mes"
        else if [MAT_COBR_DIAS] < 61 then "2 mes"
        else if [MAT_COBR_DIAS] < 91 then "3 mes"
        else if [MAT_COBR_DIAS] < 181 then "6 mes"
        else if [MAT_COBR_DIAS] < 361 then "1 ano"
        else "> 1 ano", type text
    ),

    // 6. Adição do Nome do Mês de Cobrança (mantendo "Nome do Mês.1")
    #"Nome do Mês Cobrança Inserido" = Table.AddColumn(#"MATURIDADE_ Adicionada", "Nome do Mês.1", each if [DATA_COBR] <> null then Date.MonthName([DATA_COBR]) else "A", type text),

    // 7. Normalização de UC (9 dígitos) e CIL (texto limpo)
    //    (NOVO) UC vem por vezes como número (perde o zero à esquerda) -> repõe 9 dígitos
    //    (NOVO) Lançamentos XX (VCI/Pré-pago) não são faturas: o CIL é anulado para não colidir com faturas EB
    #"UC e CIL Tratadas" = Table.AddColumn(
        Table.TransformColumns(#"Nome do Mês Cobrança Inserido", {
            {"UC", each let t = if _ = null then "" else Text.Trim(Text.From(_)) in if t = "" then "00" else Text.PadStart(t, 9, "0"), type text},
            {"cil_", each if _ = null then "" else Text.Trim(Text.From(_)), type text},
            {"TIPO_DOC", each if _ = null then "" else Text.Upper(Text.Trim(Text.From(_))), type text}
        }),
        "cil_ok", each if [TIPO_DOC] <> "XX" and Text.Length([cil_]) = 8 and Text.Select([cil_], {"0".."9"}) = [cil_] then [cil_] else "00", type text
    ),
    #"CIL Final" = Table.RenameColumns(Table.RemoveColumns(#"UC e CIL Tratadas", {"cil_"}), {{"cil_ok", "cil_"}}),

    // 8. Filtragem de Unidades Excluídas
    //    (CORREÇÃO DA DUPLICAÇÃO MAIO/JUNHO) Linhas sem UC ("00") ou sem CIL válido de 8 dígitos
    //    não pertencem a nenhum cliente identificável e, por não terem UC, escapavam ao filtro de ilhas,
    //    somando cobranças de TODAS as ilhas (ex.: Maio 755 M -> 376 M | Junho 785 M -> 432 M).
    UCsExcluir = {"010101000", "010301000", "010501000", "010502000", "010601000", "010602000", "010603000"},
    #"Linhas Filtradas" = Table.SelectRows(#"CIL Final", each
        [UC] <> "00"
        and not List.Contains(UCsExcluir, [UC])
        and [cil_] <> "00"
    ),

    // 9. Agrupamento (Sumarização dos Valores por UC, CIL, Nome do Mês.1 e MATURIDADE_)
    #"Linhas Agrupadas" = Table.Group(#"Linhas Filtradas", {"UC", "cil_", "Nome do Mês.1", "MATURIDADE_"}, {
        {"VALOR", each List.Sum([ECV]), type nullable number}
    })
in
    #"Linhas Agrupadas"
