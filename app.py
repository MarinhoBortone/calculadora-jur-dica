import streamlit as st
import pandas as pd
import requests
import calendar
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from fpdf import FPDF
import io

# --- CONFIGURAÇÃO VISUAL ---
st.set_page_config(page_title="CalcJus Pro Auditável", layout="wide")

st.title("⚖️ CalcJus PRO - Relatórios Periciais")
st.markdown("Cálculos Judiciais com **Memória de Cálculo Auditável** e **Metodologia Explícita**.")

# --- FUNÇÃO DE BUSCA NO BANCO CENTRAL (BCB) ---
@st.cache_data(ttl=3600)
def buscar_fator_bcb(codigo_serie, data_inicio, data_fim):
    if data_fim < data_inicio: return 1.0
    d1 = data_inicio.strftime("%d/%m/%Y")
    d2 = data_fim.strftime("%d/%m/%Y")
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo_serie}/dados?formato=json&dataInicial={d1}&dataFinal={d2}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            dados = response.json()
            fator = 1.0
            for item in dados:
                val = float(item['valor'])
                fator *= (1 + val/100)
            return fator
    except: pass
    return 1.0

# --- CLASSE PDF PROFISSIONAL ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 8)
        self.cell(0, 5, 'CalcJus PRO - Sistema de Cálculos Judiciais', 0, 1, 'R')
        self.line(10, 15, 287, 15) 
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 7)
        self.cell(0, 5, f'Página {self.page_no()}/{{nb}} | Documento gerado eletronicamente', 0, 0, 'C')

# --- FUNÇÃO GERADORA DE RELATÓRIO ---
def gerar_pdf_relatorio(dados_ind, dados_hon, dados_pen, totais, config):
    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.alias_nb_pages()
    pdf.add_page()
    
    # --- 1. IDENTIFICAÇÃO ---
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "DEMONSTRATIVO DE CÁLCULO JUDICIAL", ln=True, align="C")
    pdf.ln(5)
    
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", "", 10)
    
    # Metodologia
    pdf.cell(0, 8, " 1. PARÂMETROS E METODOLOGIA APLICADA", ln=True, fill=True)
    pdf.ln(2)
    
    dt_calc = config.get('data_calculo', date.today()).strftime('%d/%m/%Y')
    indice_nome = config.get('indice_nome', '-')
    regime_desc = config.get('regime_desc', '-') 
    
    texto_metodologia = (
        f"DATA BASE DO CÁLCULO: {dt_calc}\n"
        f"CRITÉRIO DE ATUALIZAÇÃO: {regime_desc}\n"
        f"ÍNDICE DE CORREÇÃO: {indice_nome} (Fonte: Banco Central/SGS)\n"
        f"CRITÉRIO DE JUROS: 1% ao mês simples (Pro-Rata Die) ou SELIC conforme regime.\n"
        f"CONVENÇÃO DE TEMPO: Mês Civil (dias efetivos do calendário).\n"
        f"FÓRMULAS APLICADAS:\n"
        f"  - Valor Atualizado = Valor Original x Fator Acumulado do Índice.\n"
        f"  - Juros Moratórios = Valor Atualizado x (Taxa% / 30 x Dias de Atraso)."
    )
    pdf.multi_cell(0, 5, texto_metodologia)
    pdf.ln(5)

    # --- 2. TABELAS ---
    
    # INDENIZAÇÃO
    if totais['indenizacao'] > 0:
        pdf.set_font("Arial", "B", 11)
        pdf.set_fill_color(200, 220, 255)
        pdf.cell(0, 8, " 2. INDENIZAÇÃO / LUCROS CESSANTES", ln=True, fill=True)
        
        pdf.set_font("Arial", "B", 8)
        # Colunas ajustadas para incluir Total Fase 1
        cols = [
            ("Vencimento", 25), 
            ("Valor Orig.", 25), 
            ("Fator CM", 20), 
            ("V. Corrigido", 25), 
            ("Juros / Mora", 40), 
            ("Total Fase 1", 30), 
            ("Fator SELIC", 20), 
            ("TOTAL FINAL", 30)
        ]
        for txt, w in cols: pdf.cell(w, 8, txt, 1, 0, 'C')
        pdf.ln()
        
        pdf.set_font("Arial", "", 8)
        for index, row in dados_ind.iterrows():
            venc = str(row['Vencimento'])
            orig = str(row['Valor Orig.'])
            f_cm = str(row.get('Audit Fator CM', row.get('Fator F1', '-')))
            v_corr = str(row.get('V. Corrigido', row.get('V. Fase 1', '-')))
            j_detalhe = str(row.get('Audit Juros %', '-'))
            if len(j_detalhe) > 25: pdf.set_font("Arial", "", 7)
            
            # AQUI ESTÁ A CORREÇÃO: Pega direto do DataFrame
            total_f1_str = str(row.get('Total Fase 1', '-'))

            f_selic = str(row.get('Audit Fator SELIC', '-'))
            total = str(row['TOTAL'])

            data_row = [venc, orig, f_cm, v_corr, j_detalhe, total_f1_str, f_selic, total]
            col_w = [25, 25, 20, 25, 40, 30, 20, 30]
            
            for i, datum in enumerate(data_row):
                align = 'L' if i == 4 else 'C'
                pdf.cell(col_w[i], 7, datum, 1, 0, align)
            pdf.set_font("Arial", "", 8)
            pdf.ln()
            
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 8, f"Subtotal Indenização: R$ {totais['indenizacao']:,.2f}", ln=True, align='R')
        pdf.ln(3)

    # HONORÁRIOS
    if totais['honorarios'] > 0:
        pdf.set_font("Arial", "B", 11)
        pdf.set_fill_color(220, 240, 220)
        pdf.cell(0, 8, " 3. HONORÁRIOS DE SUCUMBÊNCIA", ln=True, fill=True)
        pdf.set_font("Arial", "", 9)
        for index, row in dados_hon.iterrows():
             pdf.cell(0, 8, f"Descrição: {row['Descrição']} | Base: {row['Valor Orig.']} | Fator: {row.get('Audit Fator', '-')} | Juros: {row.get('Juros', '-')} | Total: {row['TOTAL']}", ln=True)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 8, f"Subtotal Honorários: R$ {totais['honorarios']:,.2f}", ln=True, align='R')
        pdf.ln(3)

    # PENSÃO
    if totais['pensao'] > 0:
        pdf.set_font("Arial", "B", 11)
        pdf.set_fill_color(255, 220, 220)
        pdf.cell(0, 8, " 4. PENSÃO ALIMENTÍCIA (DÉBITOS)", ln=True, fill=True)
        
        pdf.set_font("Arial", "B", 8)
        headers_pen = [("Vencimento", 30), ("Original", 30), (f"Fator {indice_nome}", 30), ("Atualizado", 30), ("Pago", 30), ("Saldo Devido", 40)]
        for h, w in headers_pen: pdf.cell(w, 8, h, 1, 0, 'C')
        pdf.ln()
        
        pdf.set_font("Arial", "", 8)
        for index, row in dados_pen.iterrows():
            pdf.cell(30, 8, str(row['Vencimento']), 1, 0, 'C')
            pdf.cell(30, 8, str(row['Valor Orig.']), 1, 0, 'C')
            pdf.cell(30, 8, str(row['Fator CM']), 1, 0, 'C')
            pdf.cell(30, 8, str(row['Devido Atual.']), 1, 0, 'C')
            pdf.cell(30, 8, str(row['Pago']), 1, 0, 'C')
            pdf.cell(40, 8, str(row['SALDO DEVEDOR']), 1, 0, 'C')
            pdf.ln()
        
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 8, f"Subtotal Pensão: R$ {totais['pensao']:,.2f}", ln=True, align='R')

    # --- 3. RESUMO FINAL ---
    pdf.ln(5)
    pdf.set_fill_color(200, 200, 200)
    pdf.cell(0, 8, " RESUMO FINAL DA EXECUÇÃO", ln=True, fill=True)
    
    pdf.set_font("Arial", "", 10)
    if config['multa_523']:
        pdf.cell(190, 8, "Multa Art. 523 CPC (10%)", 1)
        pdf.cell(0, 8, f"R$ {totais['multa']:,.2f}", 1, 1, 'R')
    if config['hon_523']:
        pdf.cell(190, 8, "Honorários Execução Art. 523 (10%)", 1)
        pdf.cell(0, 8, f"R$ {totais['hon_exec']:,.2f}", 1, 1, 'R')
    
    pdf.set_font("Arial", "B", 14)
    pdf.set_text_color(0, 0, 150)
    pdf.cell(190, 12, "TOTAL GERAL A PAGAR", 1)
    pdf.cell(0, 12, f"R$ {totais['final']:,.2f}", 1, 1, 'R')
    
    pdf.ln(5)
    pdf.set_font("Arial", "I", 8)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 5, "Fontes Oficiais: Banco Central do Brasil (SGS). Séries: 188 (INPC), 189 (IGP-M), 192 (INCC), 4390 (SELIC).")
    
    return pdf.output(dest='S').encode('latin-1')

# --- MENU LATERAL ---
st.sidebar.header("1. Parâmetros Gerais")
data_calculo = st.sidebar.date_input("Data do Cálculo (Atualização)", value=date.today())

mapa_indices = {"INPC (IBGE)": 188, "IGP-M (FGV)": 189, "INCC-DI": 192, "IPCA-E": 10764, "IPCA": 433}
indice_padrao_nome = st.sidebar.selectbox("Índice Base (Pré-Selic ou Padrão)", list(mapa_indices.keys()))
codigo_indice_padrao = mapa_indices[indice_padrao_nome]
cod_selic = 4390

st.sidebar.divider()
st.sidebar.header("2. Penalidades (Execução)")
aplicar_multa_523 = st.sidebar.checkbox("Aplicar Multa de 10% (Art. 523)?", value=False)
aplicar_hon_523 = st.sidebar.checkbox("Aplicar Honorários de 10%?", value=False)

# Estado
if 'total_indenizacao' not in st.session_state: st.session_state.total_indenizacao = 0.0
if 'total_honorarios' not in st.session_state: st.session_state.total_honorarios = 0.0
if 'total_pensao' not in st.session_state: st.session_state.total_pensao = 0.0
if 'df_indenizacao' not in st.session_state: st.session_state.df_indenizacao = pd.DataFrame()
if 'df_honorarios' not in st.session_state: st.session_state.df_honorarios = pd.DataFrame()
if 'df_pensao_input' not in st.session_state: st.session_state.df_pensao_input = pd.DataFrame()
if 'df_pensao_final' not in st.session_state: st.session_state.df_pensao_final = pd.DataFrame()
if 'regime_desc' not in st.session_state: st.session_state.regime_desc = "Padrão"

tab1, tab2, tab3, tab4 = st.tabs(["🏢 Indenização", "⚖️ Honorários", "👶 Pensão", "📊 PDF Final"])

# ABA 1 - INDENIZAÇÃO COM AUDITORIA
with tab1:
    st.subheader("Cálculo de Indenização / Lucros Cessantes")
    c1, c2, c3 = st.columns(3)
    valor_contrato = c1.number_input("Valor Base (Contrato/Aluguel)", value=318316.50)
    perc_indenizacao = c2.number_input("% Mensal", value=0.5)
    val_mensal = valor_contrato * (perc_indenizacao / 100)
    c3.metric("Valor Mensal", f"R$ {val_mensal:,.2f}")
    
    c4, c5 = st.columns(2)
    inicio_atraso = c4.date_input("Início da Mora", value=date(2024, 7, 1))
    fim_atraso = c5.date_input("Fim da Mora", value=date(2024, 10, 16))
    metodo_calculo = st.radio("Método de Contagem:", ["Ciclo Mensal", "Mês Civil (Pro-Rata)"], index=1, horizontal=True)
    
    st.markdown("---")
    st.write("**Regime de Atualização:**")
    tipo_regime = st.radio("Selecione:", 
        [f"1. Padrão: {indice_padrao_nome} + Juros 1%", "2. SELIC Pura", "3. Misto: Correção/Juros até Data X -> SELIC depois"],
        horizontal=True
    )
    
    data_corte_selic = None
    data_citacao_ind = None
    
    if "3. Misto" in tipo_regime:
        c_mix1, c_mix2 = st.columns(2)
        data_citacao_ind = c_mix1.date_input("Data Citação (Início Juros Fase 1)", value=date(2024, 3, 1))
        data_corte_selic = c_mix2.date_input("Data Início SELIC (Corte)", value=date(2024, 12, 1))
        st.session_state.regime_desc = f"Misto ({indice_padrao_nome} + Juros 1% até {data_corte_selic.strftime('%d/%m/%Y')} -> SELIC acumulada)"
    elif "1. Padrão" in tipo_regime:
        data_citacao_ind = st.date_input("Data Citação (Início Juros)", value=date(2025, 2, 25))
        st.session_state.regime_desc = f"Padrão ({indice_padrao_nome} + Juros 1% a.m.)"
    else:
        st.session_state.regime_desc = "SELIC Pura (EC 113/21)"
        st.info("ℹ️ Regime SELIC Pura: Aplica-se a taxa SELIC (que engloba juros e correção) desde o vencimento.")

    if st.button("Calcular Indenização", type="primary"):
        lista_ind = []
        progresso = st.progress(0, text="Buscando índices...")
        
        # GERAÇÃO DE DATAS
        datas_vencimento = []
        valores_base = []
        
        if metodo_calculo == "Ciclo Mensal":
             t_date = inicio_atraso
             while t_date < fim_atraso:
                 prox = t_date + relativedelta(months=1)
                 venc = prox - timedelta(days=1)
                 if venc > fim_atraso: venc = fim_atraso
                 datas_vencimento.append(venc)
                 valores_base.append(val_mensal) 
                 t_date = prox.replace(day=1)
        else:
            curr_date = inicio_atraso.replace(day=1)
            end_date_ref = fim_atraso.replace(day=1)
            meses_list = []
            while curr_date <= end_date_ref:
                meses_list.append(curr_date)
                curr_date += relativedelta(months=1)
            
            for mes_ref in meses_list:
                ult_dia = mes_ref.replace(day=calendar.monthrange(mes_ref.year, mes_ref.month)[1])
                ini_ef = inicio_atraso if mes_ref.year == inicio_atraso.year and mes_ref.month == inicio_atraso.month else mes_ref
                fim_ef = fim_atraso if mes_ref.year == fim_atraso.year and mes_ref.month == fim_atraso.month else ult_dia
                d_mes = calendar.monthrange(mes_ref.year, mes_ref.month)[1]
                d_corr = (fim_ef - ini_ef).days + 1
                val = val_mensal if (ini_ef.day == 1 and fim_ef.day == ult_dia.day) else (val_mensal / d_mes) * d_corr
                datas_vencimento.append(fim_ef)
                valores_base.append(val)

        # CÁLCULO
        for i, venc in enumerate(datas_vencimento):
            val_base = valores_base[i]
            progresso.progress((i + 1) / len(datas_vencimento))
            
            audit_fator_cm = "-"
            audit_juros_perc = "-"
            audit_fator_selic = "-"
            v_base_selic_str = "-" # Valor que será impresso na coluna
            
            total_final = 0.0
            v_fase1 = 0.0
            
            if "1. Padrão" in tipo_regime:
                fator = buscar_fator_bcb(codigo_indice_padrao, venc, data_calculo)
                v_fase1 = val_base * fator
                audit_fator_cm = f"{fator:.5f}" 
                
                dt_j = data_citacao_ind if venc < data_citacao_ind else venc
                dias = (data_calculo - dt_j).days
                juros_val = v_fase1 * (0.01/30 * dias) if dias > 0 else 0.0
                perc_juros = (dias/30) 
                audit_juros_perc = f"{perc_juros:.1f}% ({dias}d)"
                
                total_final = v_fase1 + juros_val

            elif "2. SELIC" in tipo_regime:
                fator = buscar_fator_bcb(cod_selic, venc, data_calculo)
                total_final = val_base * fator
                audit_fator_selic = f"{fator:.5f}"
                v_fase1 = total_final 
            
            elif "3. Misto" in tipo_regime:
                if venc >= data_corte_selic:
                    fator = buscar_fator_bcb(cod_selic, venc, data_calculo)
                    total_final = val_base * fator
                    audit_fator_selic = f"{fator:.5f}"
                    v_fase1 = total_final
                else:
                    fator_f1 = buscar_fator_bcb(codigo_indice_padrao, venc, data_corte_selic)
                    v_f1 = val_base * fator_f1
                    audit_fator_cm = f"{fator_f1:.5f}"
                    
                    dt_j = data_citacao_ind if venc < data_citacao_ind else venc
                    if dt_j < data_corte_selic:
                        d_f1 = (data_corte_selic - dt_j).days
                        j_f1 = v_f1 * (0.01/30 * d_f1)
                        perc_j1 = (d_f1/30)
                        audit_juros_perc = f"{perc_j1:.1f}% ({d_f1}d F1)"
                    else:
                        j_f1 = 0.0
                    
                    base_selic = v_f1 + j_f1
                    # Armazena para a tabela
                    v_base_selic_str = f"R$ {base_selic:,.2f}"
                    
                    fator_s = buscar_fator_bcb(cod_selic, data_corte_selic, data_calculo)
                    total_final = base_selic * fator_s
                    audit_fator_selic = f"{fator_s:.5f}"
                    v_fase1 = base_selic 

            lista_ind.append({
                "Vencimento": venc.strftime("%d/%m/%Y"), 
                "Valor Orig.": f"R$ {val_base:,.2f}", 
                "Audit Fator CM": audit_fator_cm,
                "V. Corrigido": f"R$ {v_fase1:,.2f}" if v_fase1 > 0 else "-", 
                "Audit Juros %": audit_juros_perc,
                "Audit Fator SELIC": audit_fator_selic,
                "Total Fase 1": v_base_selic_str, # COLUNA NOVA PREENCHIDA
                "TOTAL": f"R$ {total_final:,.2f}", 
                "_num": total_final
            })
            
        progresso.empty()
        df = pd.DataFrame(lista_ind)
        st.session_state.df_indenizacao = df
        st.session_state.total_indenizacao = df["_num"].sum()
        st.success(f"Total: R$ {st.session_state.total_indenizacao:,.2f}")
        st.dataframe(df.drop(columns=["_num"]), use_container_width=True)

# ABA 2 - HONORÁRIOS
with tab2:
    st.subheader("Cálculo de Honorários")
    v_h = st.number_input("Valor", 1500.00)
    d_h = st.date_input("Data Base", date(2024, 12, 3))
    if st.button("Calcular Honorários"):
        f = buscar_fator_bcb(codigo_indice_padrao, d_h, data_calculo)
        tot = v_h * f
        res = [{"Descrição": "Honorários", "Valor Orig.": f"R$ {v_h:.2f}", "Audit Fator": f"{f:.5f}", "Juros": "0,00", "TOTAL": f"R$ {tot:.2f}", "_num": tot}]
        st.session_state.df_honorarios = pd.DataFrame(res)
        st.session_state.total_honorarios = tot
        st.success(f"Total: R$ {tot:.2f}")

# ABA 3 - PENSÃO
with tab3:
    st.subheader("👶 Pensão Alimentícia")
    c1, c2 = st.columns(2)
    v_pensao = c1.number_input("Valor", value=1000.00)
    dia = c2.number_input("Dia", value=10, min_value=1, max_value=31)
    c3, c4 = st.columns(2)
    ini = c3.date_input("Início", value=date(2023, 1, 1))
    fim = c4.date_input("Fim", value=date.today())
    
    if st.button("1. Gerar Tabela"):
        l = []
        dt = ini.replace(day=dia) if dia <= 28 else ini
        if dt < ini: dt += relativedelta(months=1)
        while dt <= fim:
            l.append({"Vencimento": dt, "Valor Devido (R$)": float(v_pensao), "Valor Pago (R$)": 0.0})
            dt += relativedelta(months=1)
        st.session_state.df_pensao_input = pd.DataFrame(l)

    if not st.session_state.df_pensao_input.empty:
        st.write("👇 **Edite abaixo os valores pagos:**")
        tabela_editada = st.data_editor(st.session_state.df_pensao_input, num_rows="dynamic", hide_index=True)
        
        if st.button("2. Calcular Saldo"):
            res_p = []
            for i, r in edited.iterrows():
                venc = pd.to_datetime(r["Vencimento"]).date()
                v_orig = row["Valor Devido (R$)"]
                v_pago = row["Valor Pago (R$)"]
                fator = buscar_fator_bcb(codigo_indice_padrao, venc, data_calculo)
                v_corr = v_orig * fator
                juros = 0.0
                dias = (data_calculo - venc).days
                if dias > 0: juros = v_corr * (0.01/30 * dias)
                total_bruto = v_corr + juros
                saldo_mes = total_bruto - v_pago
                res_p.append({
                    "Vencimento": venc.strftime("%d/%m/%Y"), 
                    "Valor Orig.": f"R$ {v_orig:,.2f}", 
                    "Fator CM": f"{fator:.6f}", 
                    "Devido Atual.": f"R$ {v_corr:,.2f}", 
                    "Juros": f"R$ {juros:,.2f}", 
                    "SALDO DEVEDOR": f"R$ {saldo_mes:,.2f}", 
                    "_num": saldo_mes
                })
            st.session_state.df_pensao_final = pd.DataFrame(res_p)
            st.session_state.total_pensao = st.session_state.df_pensao_final["_num"].sum()
            st.success(f"Saldo: R$ {st.session_state.total_pensao:,.2f}")

# ABA 4 - RESUMO
with tab4:
    st.subheader("Resumo Global")
    t1 = st.session_state.total_indenizacao
    t2 = st.session_state.total_honorarios
    t3 = st.session_state.total_pensao
    
    sub = t1 + t2 + t3
    mul = sub * 0.10 if aplicar_multa_523 else 0.0
    hon = sub * 0.10 if aplicar_hon_523 else 0.0
    fin = sub + mul + hon
    
    st.write(f"**Subtotal:** R$ {sub:,.2f}")
    if aplicar_multa_523: st.write(f"+ Multa 10%: R$ {mul:,.2f}")
    if aplicar_hon_523: st.write(f"+ Honorários 10%: R$ {hon:,.2f}")
    st.metric("TOTAL FINAL", f"R$ {fin:,.2f}")
    
    tot_pdf = {'indenizacao': t1, 'honorarios': t2, 'pensao': t3, 'multa': mul, 'hon_exec': hon, 'final': fin}
    conf_pdf = {'multa_523': aplicar_multa_523, 'hon_523': aplicar_hon_523, 'metodo': metodo_calculo, 'indice_nome': indice_padrao_nome, 'data_calculo': data_calculo, 'regime_desc': st.session_state.regime_desc}
    
    if st.button("Gerar PDF Oficial"):
        b = gerar_pdf_relatorio(st.session_state.df_indenizacao, st.session_state.df_honorarios, st.session_state.df_pensao_final, tot_pdf, conf_pdf)
        st.download_button("Baixar PDF", b, "memoria_calculo.pdf", "application/pdf")
