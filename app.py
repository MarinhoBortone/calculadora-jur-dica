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
st.markdown("Cálculos Judiciais com **Memória de Cálculo Auditável** (Fatores Explícitos).")

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

# --- GERADOR DE PDF PROFISSIONAL ---
def gerar_pdf_relatorio(dados_ind, dados_hon, dados_pen, totais, config):
    pdf = FPDF(orientation='L', unit='mm', format='A4') # Paisagem
    pdf.add_page()
    
    # Cabeçalho
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "MEMÓRIA DE CÁLCULO JUDICIAL DETALHADA", ln=True, align="C")
    pdf.set_font("Arial", "", 9)
    pdf.cell(0, 6, f"Emissão: {datetime.now().strftime('%d/%m/%Y %H:%M')} | Método: {config.get('metodo', '-')}", ln=True, align="C")
    pdf.ln(5)
    
    # --- BLOCO INDENIZAÇÃO ---
    if totais['indenizacao'] > 0:
        pdf.set_font("Arial", "B", 11)
        pdf.set_fill_color(220, 230, 240)
        pdf.cell(0, 8, "1. INDENIZAÇÃO / LUCROS CESSANTES", ln=True, fill=True)
        
        # Cabeçalho da Tabela (Auditável)
        pdf.set_font("Arial", "B", 8)
        # Colunas Otimizadas para Auditoria
        cols = [
            ("Vencimento", 25), 
            ("Valor Base", 30), 
            ("Fator CM (Índice)", 30), 
            ("Valor Corrigido", 30), 
            ("Juros (%)", 25), 
            ("Fator SELIC", 30), 
            ("TOTAL FINAL", 35)
        ]
        
        for txt, w in cols:
            pdf.cell(w, 8, txt, 1, 0, 'C')
        pdf.ln()
        
        pdf.set_font("Arial", "", 8)
        for index, row in dados_ind.iterrows():
            # Pega dados formatados ou traço se não existir
            venc = str(row['Vencimento'])
            orig = str(row['Valor Orig.'])
            # Lógica para pegar o fator correto dependendo do regime
            f_cm = str(row.get('Audit Fator CM', row.get('Fator F1', '-')))
            v_corr = str(row.get('V. Corrigido', row.get('V. Fase 1', '-')))
            jur_p = str(row.get('Audit Juros %', '-'))
            f_selic = str(row.get('Audit Fator SELIC', '-'))
            total = str(row['TOTAL'])

            data_row = [venc, orig, f_cm, v_corr, jur_p, f_selic, total]
            
            for i, datum in enumerate(data_row):
                pdf.cell(cols[i][1], 7, datum, 1, 0, 'C')
            pdf.ln()
            
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 10, f"Subtotal Indenização: R$ {totais['indenizacao']:,.2f}", ln=True, align='R')
        pdf.ln(3)

    # --- BLOCO HONORÁRIOS ---
    if totais['honorarios'] > 0:
        pdf.set_font("Arial", "B", 11)
        pdf.set_fill_color(220, 240, 220)
        pdf.cell(0, 8, "2. HONORÁRIOS DE SUCUMBÊNCIA", ln=True, fill=True)
        pdf.set_font("Arial", "", 9)
        for index, row in dados_hon.iterrows():
             pdf.cell(0, 8, f"{row['Descrição']} | Base: {row['Valor Orig.']} | Fator: {row.get('Audit Fator', '-')} | Juros: {row.get('Juros', '-')} | Total: {row['TOTAL']}", ln=True)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 10, f"Subtotal Honorários: R$ {totais['honorarios']:,.2f}", ln=True, align='R')
        pdf.ln(3)

    # --- BLOCO PENSÃO ---
    if totais['pensao'] > 0:
        pdf.set_font("Arial", "B", 12)
        pdf.set_fill_color(255, 220, 220)
        pdf.cell(0, 10, "3. Pensão Alimentícia", ln=True, fill=True)
        pdf.set_font("Arial", "B", 8)
        
        headers_pen = [("Vencimento", 30), ("Original", 30), ("Fator CM", 25), ("Atualizado", 30), ("Pago", 30), ("Saldo", 30)]
        for h, w in headers_pen: pdf.cell(w, 8, h, 1)
        pdf.ln()
        
        pdf.set_font("Arial", "", 8)
        for index, row in dados_pen.iterrows():
            pdf.cell(30, 8, str(row['Vencimento']), 1)
            pdf.cell(30, 8, str(row['Valor Orig.']), 1)
            pdf.cell(25, 8, str(row['Fator CM']), 1)
            pdf.cell(30, 8, str(row['Devido Atual.']), 1)
            pdf.cell(30, 8, str(row['Pago']), 1)
            pdf.cell(30, 8, str(row['SALDO DEVEDOR']), 1, ln=True)
        
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 10, f"Subtotal Pensão: R$ {totais['pensao']:,.2f}", ln=True, align='R')

    # TOTAL GERAL
    pdf.ln(5)
    if config['multa_523']:
        pdf.cell(0, 8, f"Multa Art. 523 (10%): R$ {totais['multa']:,.2f}", ln=True, align='R')
    if config['hon_523']:
        pdf.cell(0, 8, f"Honorários Execução (10%): R$ {totais['hon_exec']:,.2f}", ln=True, align='R')
    
    pdf.set_font("Arial", "B", 14)
    pdf.set_text_color(0, 0, 150)
    pdf.cell(0, 12, f"TOTAL DA EXECUÇÃO: R$ {totais['final']:,.2f}", ln=True, align='R')
    
    return pdf.output(dest='S').encode('latin-1')

# --- MENU LATERAL ---
st.sidebar.header("1. Parâmetros Gerais")
data_calculo = st.sidebar.date_input("Data do Cálculo (Atualização)", value=date.today())

mapa_indices = {"INPC (IBGE)": 188, "IGP-M (FGV)": 189, "INCC-DI": 192, "IPCA-E": 10764, "IPCA": 433}
indice_padrao_nome = st.sidebar.selectbox("Índice Base (Pré-Selic ou Padrão)", list(mapa_indices.keys()))
codigo_indice_padrao = mapa_indices[indice_padrao_nome]
cod_selic = 4390

st.sidebar.divider()
st.sidebar.header("2. Penalidades")
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
    st.write("**Regra de Atualização:**")
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
    elif "1. Padrão" in tipo_regime:
        data_citacao_ind = st.date_input("Data Citação (Início Juros)", value=date(2025, 2, 25))

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
                 valores_base.append(val_mensal) # Simplificado
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

        # CÁLCULO DETALHADO
        for i, venc in enumerate(datas_vencimento):
            val_base = valores_base[i]
            progresso.progress((i + 1) / len(datas_vencimento))
            
            # Variáveis de Auditoria (Fatores Explícitos)
            audit_fator_cm = "-"
            audit_juros_perc = "-"
            audit_fator_selic = "-"
            
            total_final = 0.0
            v_fase1 = 0.0
            
            if "1. Padrão" in tipo_regime:
                fator = buscar_fator_bcb(codigo_indice_padrao, venc, data_calculo)
                v_fase1 = val_base * fator
                audit_fator_cm = f"{fator:.5f}"
                
                dt_j = data_citacao_ind if venc < data_citacao_ind else venc
                dias = (data_calculo - dt_j).days
                juros_val = v_fase1 * (0.01/30 * dias) if dias > 0 else 0.0
                perc_juros = (dias/30) # % acumulado aproximado
                audit_juros_perc = f"{perc_juros:.1f}%"
                
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
                    # Fase 1 (INPC + Juros)
                    fator_f1 = buscar_fator_bcb(codigo_indice_padrao, venc, data_corte_selic)
                    v_f1 = val_base * fator_f1
                    audit_fator_cm = f"{fator_f1:.5f}"
                    
                    dt_j = data_citacao_ind if venc < data_citacao_ind else venc
                    if dt_j < data_corte_selic:
                        d_f1 = (data_corte_selic - dt_j).days
                        j_f1 = v_f1 * (0.01/30 * d_f1)
                        perc_j1 = (d_f1/30)
                        audit_juros_perc = f"{perc_j1:.1f}% (F1)"
                    else:
                        j_f1 = 0.0
                    
                    base_selic = v_f1 + j_f1
                    
                    # Fase 2 (SELIC)
                    fator_s = buscar_fator_bcb(cod_selic, data_corte_selic, data_calculo)
                    total_final = base_selic * fator_s
                    audit_fator_selic = f"{fator_s:.5f}"
                    v_fase1 = base_selic # Valor base para SELIC

            lista_ind.append({
                "Vencimento": venc.strftime("%d/%m/%Y"),
                "Valor Orig.": f"R$ {val_base:,.2f}",
                "Audit Fator CM": audit_fator_cm,
                "V. Corrigido": f"R$ {v_fase1:,.2f}" if v_fase1 > 0 else "-",
                "Audit Juros %": audit_juros_perc,
                "Audit Fator SELIC": audit_fator_selic,
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
        res = [{"Descrição": "Honorários", "Valor Orig.": f"R$ {v_h:.2f}", "Audit Fator": f"{f:.5f}", "TOTAL": f"R$ {tot:.2f}", "_num": tot}]
        st.session_state.df_honorarios = pd.DataFrame(res)
        st.session_state.total_honorarios = tot
        st.success(f"Total: R$ {tot:.2f}")

# ABA 4 - RESUMO
with tab4:
    st.subheader("Relatório Final")
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
    conf_pdf = {'multa_523': aplicar_multa_523, 'hon_523': aplicar_hon_523, 'metodo': metodo_calculo}
    
    if st.button("Gerar PDF Oficial"):
        b = gerar_pdf_relatorio(st.session_state.df_indenizacao, st.session_state.df_honorarios, st.session_state.df_pensao_final, tot_pdf, conf_pdf)
        st.download_button("Baixar PDF", b, "memoria_calculo.pdf", "application/pdf")
