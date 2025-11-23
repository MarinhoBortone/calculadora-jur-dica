import streamlit as st
import pandas as pd
import requests
import calendar
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from fpdf import FPDF
import io

# --- CONFIGURAÇÃO VISUAL ---
st.set_page_config(page_title="CalcJus Pro", layout="wide")

st.title("⚖️ CalcJus PRO - Central de Cálculos Judiciais")
st.markdown("Cálculos de **Indenizações**, **Honorários** e **Pensão Alimentícia** com Relatório PDF e opção SELIC.")

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

# --- FUNÇÃO GERADORA DE PDF ---
def gerar_pdf_relatorio(dados_ind, dados_hon, dados_pen, totais, config):
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "Relatório de Cálculo Judicial", ln=True, align="C")
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 10, f"Data de Emissão: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    pdf.ln(5)
    
    # BLOCO INDENIZAÇÃO
    if totais['indenizacao'] > 0:
        pdf.set_font("Arial", "B", 12)
        pdf.set_fill_color(200, 220, 255)
        pdf.cell(0, 10, "1. Indenização Cível / Lucros Cessantes", ln=True, fill=True)
        pdf.set_font("Arial", "", 8)
        
        col_w = [25, 25, 40, 25, 25, 25, 30]
        headers = ["Vencimento", "Valor Base", "Regra/Índice", "V. Fase 1", "Juros Fase 1", "V. Base SELIC", "TOTAL FINAL"]
        
        for i, h in enumerate(headers):
            pdf.cell(col_w[i], 8, h, 1)
        pdf.ln()
        
        for index, row in dados_ind.iterrows():
            regra = str(row.get('Regra', '-'))
            v_f1 = str(row.get('V. Fase 1', '-'))
            j_f1 = str(row.get('Juros F1', '-'))
            v_selic = str(row.get('Base SELIC', '-'))
            
            pdf.cell(col_w[0], 8, str(row['Vencimento']), 1)
            pdf.cell(col_w[1], 8, str(row['Valor Orig.']), 1)
            pdf.cell(col_w[2], 8, regra[:25], 1)
            pdf.cell(col_w[3], 8, v_f1, 1)
            pdf.cell(col_w[4], 8, j_f1, 1)
            pdf.cell(col_w[5], 8, v_selic, 1)
            pdf.cell(col_w[6], 8, str(row['TOTAL']), 1, ln=True)
        
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 10, f"Subtotal Indenização: R$ {totais['indenizacao']:,.2f}", ln=True, align='R')
        pdf.ln(5)

    # BLOCO HONORÁRIOS
    if totais['honorarios'] > 0:
        pdf.set_font("Arial", "B", 12)
        pdf.set_fill_color(220, 255, 220)
        pdf.cell(0, 10, "2. Honorários de Sucumbência", ln=True, fill=True)
        pdf.set_font("Arial", "", 10)
        for index, row in dados_hon.iterrows():
             pdf.cell(0, 10, f"{row['Descrição']}: R$ {row['TOTAL']}", ln=True)
        pdf.cell(0, 10, f"Subtotal Honorários: R$ {totais['honorarios']:,.2f}", ln=True, align='R')
        pdf.ln(5)

    # BLOCO PENSÃO
    if totais['pensao'] > 0:
        pdf.set_font("Arial", "B", 12)
        pdf.set_fill_color(255, 220, 220)
        pdf.cell(0, 10, "3. Pensão Alimentícia (Débitos)", ln=True, fill=True)
        pdf.set_font("Arial", "", 9)
        
        pdf.cell(30, 8, "Vencimento", 1)
        pdf.cell(30, 8, "Devido Orig.", 1)
        pdf.cell(30, 8, "Pago", 1)
        pdf.cell(30, 8, "Juros", 1)
        pdf.cell(0, 8, "Saldo Devedor", 1, ln=True)
        
        for index, row in dados_pen.iterrows():
            pdf.cell(30, 8, str(row['Vencimento']), 1)
            pdf.cell(30, 8, str(row['Devido Orig.']), 1)
            pdf.cell(30, 8, str(row['Pago']), 1)
            pdf.cell(30, 8, str(row['Juros']), 1)
            pdf.cell(0, 8, str(row['SALDO DEVEDOR']), 1, ln=True)
            
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 10, f"Subtotal Pensão: R$ {totais['pensao']:,.2f}", ln=True, align='R')
        pdf.ln(5)

    # TOTAL GERAL
    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 0, "", "T")
    pdf.ln(5)
    if config['multa_523']:
        pdf.cell(0, 8, f"Multa Art. 523 (10%): R$ {totais['multa']:,.2f}", ln=True, align='R')
    if config['hon_523']:
        pdf.cell(0, 8, f"Honorários Execução (10%): R$ {totais['hon_exec']:,.2f}", ln=True, align='R')
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 15, f"TOTAL FINAL DA EXECUÇÃO: R$ {totais['final']:,.2f}", ln=True, align='R', border=1)
    return pdf.output(dest='S').encode('latin-1')

# --- MENU LATERAL ---
st.sidebar.header("1. Parâmetros Gerais")
data_calculo = st.sidebar.date_input("Data do Cálculo (Atualização)", value=date.today())

# Listas de Índices (Para fase pré-SELIC ou Padrão)
mapa_indices = {
    "INPC (IBGE)": 188, 
    "IGP-M (FGV)": 189, 
    "INCC-DI": 192, 
    "IPCA-E": 10764, 
    "IPCA": 433
}
indice_padrao_nome = st.sidebar.selectbox("Índice de Correção (Fase Pré-Selic ou Padrão)", list(mapa_indices.keys()))
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

tab1, tab2, tab3, tab4 = st.tabs(["🏢 1. Indenização Cível", "⚖️ 2. Honorários", "👶 3. Pensão Alimentícia", "📊 4. RESUMO E PDF"])

# ABA 1 - INDENIZAÇÃO
with tab1:
    st.subheader("Cálculo de Indenização / Lucros Cessantes")
    c1, c2, c3 = st.columns(3)
    valor_contrato = c1.number_input("Valor Base (Contrato/Aluguel)", value=318316.50, step=1000.00)
    perc_indenizacao = c2.number_input("% Mensal (100% = valor cheio)", value=0.5, step=0.1)
    valor_mensal_cheio = valor_contrato * (perc_indenizacao / 100)
    c3.metric("Valor Mensal Cheio", f"R$ {valor_mensal_cheio:,.2f}")
    
    c4, c5 = st.columns(2)
    inicio_atraso = c4.date_input("Início da Mora", value=date(2024, 7, 1))
    fim_atraso = c5.date_input("Fim da Mora", value=date(2024, 10, 16))
    
    c6, c7 = st.columns(2)
    metodo_calculo = c7.radio("Método de Contagem:", ["Ciclo Mensal", "Mês Civil (Pro-Rata)"], index=1)
    
    # --- SELETOR DE REGIME ---
    st.write("---")
    st.write("**Regime de Atualização:**")
    tipo_regime = st.radio(
        "Escolha a regra judicial:",
        [
            f"1. Padrão: Correção ({indice_padrao_nome}) + Juros 1% a.m.", 
            "2. SELIC Pura (Todo o período)",
            "3. Misto: Correção + Juros até DATA X -> SELIC a partir de DATA X"
        ],
        index=0
    )
    
    data_corte_selic = None
    data_citacao_ind = None
    
    if "3. Misto" in tipo_regime:
        col_mix1, col_mix2 = st.columns(2)
        data_citacao_ind = col_mix1.date_input("Data Citação (Início Juros Fase 1)", value=date(2024, 3, 1))
        data_corte_selic = col_mix2.date_input("Data de Início da SELIC (Transição)", value=date(2024, 12, 1), help="Até esta data calcula-se Índice + Juros. O total acumulado passa a ser corrigido pela SELIC.")
    elif "1. Padrão" in tipo_regime:
        data_citacao_ind = st.date_input("Data da Citação (Início Juros)", value=date(2025, 2, 25))
    else:
        st.info("ℹ️ Regime SELIC Pura: Aplica-se a taxa SELIC (que engloba juros e correção) desde o vencimento.")

    if st.button("Calcular Indenização", type="primary"):
        lista_ind = []
        progresso = st.progress(0, text="Buscando índices...")
        
        datas_vencimento = []
        valores_base = []
        
        if metodo_calculo == "Ciclo Mensal":
             t_date = inicio_atraso
             while t_date < fim_atraso:
                 prox = t_date + relativedelta(months=1)
                 venc = prox - timedelta(days=1)
                 fator_pro_rata = 1.0
                 if venc > fim_atraso:
                     d_mes = (venc - t_date).days + 1
                     d_pro = (fim_atraso - t_date).days + 1
                     fator_pro_rata = d_pro / d_mes
                     venc = fim_atraso
                 datas_vencimento.append(venc)
                 valores_base.append(valor_mensal_cheio * fator_pro_rata)
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
                val = valor_mensal_cheio if (ini_ef.day == 1 and fim_ef.day == ult_dia.day) else (valor_mensal_cheio / d_mes) * d_corr
                datas_vencimento.append(fim_ef)
                valores_base.append(val)

        for i, venc in enumerate(datas_vencimento):
            val_base = valores_base[i]
            progresso.progress((i + 1) / len(datas_vencimento))
            
            fator_f1_str = "-"
            fator_selic_str = "-"
            juros_detalhe = "-"
            
            total_final = 0.0
            v_fase1 = 0.0
            
            if "1. Padrão" in tipo_regime:
                fator = buscar_fator_bcb(codigo_indice_padrao, venc, data_calculo)
                v_fase1 = val_base * fator
                fator_f1_str = f"{fator:.6f}"
                
                dt_juros = data_citacao_ind if venc < data_citacao_ind else venc
                dias = (data_calculo - dt_juros).days
                juros_val = v_fase1 * (0.01/30 * dias) if dias > 0 else 0.0
                juros_detalhe = f"{dias} dias (R$ {juros_val:.2f})"
                
                total_final = v_fase1 + juros_val

            elif "2. SELIC" in tipo_regime:
                fator = buscar_fator_bcb(cod_selic, venc, data_calculo)
                total_final = val_base * fator
                fator_selic_str = f"{fator:.6f}"
                juros_detalhe = "Incluso na SELIC"
            
            elif "3. Misto" in tipo_regime:
                if venc >= data_corte_selic:
                    fator = buscar_fator_bcb(cod_selic, venc, data_calculo)
                    total_final = val_base * fator
                    fator_selic_str = f"{fator:.6f}"
                    juros_detalhe = "SELIC (Pós-Corte)"
                else:
                    fator_f1 = buscar_fator_bcb(codigo_indice_padrao, venc, data_corte_selic)
                    v_fase1 = val_base * fator_f1
                    fator_f1_str = f"{fator_f1:.6f}"
                    
                    dt_j = data_citacao_ind if venc < data_citacao_ind else venc
                    if dt_j < data_corte_selic:
                        d_f1 = (data_corte_selic - dt_j).days
                        j_f1 = v_fase1 * (0.01/30 * d_f1)
                        juros_detalhe = f"F1: {d_f1} dias (R$ {j_f1:.2f})"
                    else:
                        j_f1 = 0.0
                    
                    base_selic = v_fase1 + j_f1
                    fator_s = buscar_fator_bcb(cod_selic, data_corte_selic, data_calculo)
                    total_final = base_selic * fator_s
                    fator_selic_str = f"{fator_s:.6f}"

            lista_ind.append({
                "Vencimento": venc.strftime("%d/%m/%Y"), 
                "Valor Orig.": f"R$ {val_base:,.2f}", 
                "Regra": str(tipo_regime)[:20]+"...",
                "V. Fase 1": f"R$ {v_fase1:,.2f}" if v_fase1 > 0 else "-", 
                "Juros F1": juros_detalhe, 
                "Base SELIC": f"R$ {base_selic if 'base_selic' in locals() else 0:,.2f}",
                "TOTAL": f"R$ {total_final:,.2f}", 
                "_num": total_final
            })
            
        progresso.empty()
        df = pd.DataFrame(lista_ind)
        st.session_state.df_indenizacao = df
        st.session_state.total_indenizacao = df["_num"].sum()
        st.success(f"Total: R$ {st.session_state.total_indenizacao:,.2f}")
        st.dataframe(df.drop(columns=["_num"]), use_container_width=True)

# ABA 2 - HONORÁRIOS (Mantida Simples)
with tab2:
    st.subheader("Cálculo de Honorários")
    v_hon = st.number_input("Valor Honorários", value=1500.00)
    d_base = st.date_input("Correção desde", value=date(2024, 12, 3))
    
    if st.button("Calcular Honorários"):
        fator = buscar_fator_bcb(codigo_indice_padrao, d_base, data_calculo)
        tot = v_hon * fator
        res = [{"Descrição": "Honorários", "Valor Orig.": f"R$ {v_hon:.2f}", "Fator": f"{fator:.6f}", "TOTAL": f"R$ {tot:.2f}", "_num": tot}]
        st.session_state.df_honorarios = pd.DataFrame(res)
        st.session_state.total_honorarios = tot
        st.success(f"Total: R$ {tot:.2f}")

# ABA 3 - PENSÃO (Corrigida)
with tab3:
    st.subheader("👶 Pensão Alimentícia")
    c1, c2 = st.columns(2)
    v_pensao = c1.number_input("Valor", value=1000.00)
    # --- CORREÇÃO DO ERRO AQUI: Usando value=10 explicitamente ---
    dia = c2.number_input("Dia", value=10, min_value=1, max_value=31) 
    
    c3, c4 = st.columns(2)
    ini = c3.date_input("Início", value=date(2023, 1, 1))
    fim = c4.date_input("Fim", value=date.today())
    usar_juros_pen = st.checkbox("Aplicar Juros de Mora (1% a.m.)?", value=True, key="ck_juros_pen")
    
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
                if usar_juros_pen:
                    dias = (data_calculo - venc).days
                    juros = v_corr * (0.01/30 * dias) if dias > 0 else 0.0
                total_bruto = v_corr + juros
                saldo_mes = total_bruto - v_pago
                res_p.append({"Vencimento": venc.strftime("%d/%m/%Y"), "Devido Orig.": f"R$ {v_orig:,.2f}", "Pago": f"R$ {v_pago:,.2f}", "Devido Atual.": f"R$ {v_corr:,.2f}", "Juros": f"R$ {juros:,.2f}", "SALDO DEVEDOR": f"R$ {saldo_mes:,.2f}", "_num": saldo_mes})
                
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
    conf_pdf = {'multa_523': aplicar_multa_523, 'hon_523': aplicar_hon_523}
    
    if st.button("Gerar PDF"):
        b = gerar_pdf_relatorio(st.session_state.df_indenizacao, st.session_state.df_honorarios, st.session_state.df_pensao_final, tot_pdf, conf_pdf)
        st.download_button("Baixar PDF", b, "calculo.pdf", "application/pdf")
