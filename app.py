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
                # Se for SELIC (4390), a taxa é percentual. Se for índice, é variação.
                # A matemática financeira básica é (1 + taxa/100) acumulado.
                fator *= (1 + val/100)
            return fator
    except: pass
    return 1.0

# --- FUNÇÃO GERADORA DE PDF ---
def gerar_pdf_relatorio(dados_ind, dados_hon, dados_pen, totais, config):
    pdf = FPDF()
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
        pdf.set_font("Arial", "", 9)
        
        # Cabeçalho
        pdf.cell(25, 8, "Vencim.", 1)
        pdf.cell(25, 8, "Valor Base", 1)
        pdf.cell(35, 8, "Índice/Fator", 1) # Aumentei largura
        pdf.cell(25, 8, "V. Atual.", 1)
        pdf.cell(30, 8, "Juros/Mora", 1) # Aumentei largura
        pdf.cell(0, 8, "Total", 1, ln=True)
        
        for index, row in dados_ind.iterrows():
            pdf.cell(25, 8, str(row['Vencimento']), 1)
            pdf.cell(25, 8, str(row['Valor Orig.']), 1)
            pdf.cell(35, 8, str(row['Fator']), 1)
            pdf.cell(25, 8, str(row['V. Corrigido']), 1)
            pdf.cell(30, 8, str(row['Juros (R$)']), 1)
            pdf.cell(0, 8, str(row['TOTAL']), 1, ln=True)
        
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 10, f"Subtotal Indenização: R$ {totais['indenizacao']:,.2f}", ln=True, align='R')
        pdf.ln(5)

    # BLOCO HONORÁRIOS
    if totais['honorarios'] > 0:
        pdf.set_font("Arial", "B", 12)
        pdf.set_fill_color(220, 255, 220)
        pdf.cell(0, 10, "2. Honorários de Sucumbência / Custas", ln=True, fill=True)
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

    # --- BLOCO TOTAL GERAL ---
    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 0, "", "T") # Linha separadora
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

# Listas de Índices
mapa_indices = {
    "INPC (IBGE)": 188, 
    "IGP-M (FGV)": 189, 
    "INCC-DI": 192, 
    "IPCA-E": 10764, 
    "IPCA": 433, 
    "Taxa SELIC (EC 113/21)": 4390
}
# Aqui escolhemos o índice PADRÃO. A opção SELIC para Juros será feita abaixo, caso a caso.
indice_padrao_nome = st.sidebar.selectbox("Índice de Correção Padrão", list(mapa_indices.keys()))
codigo_indice_padrao = mapa_indices[indice_padrao_nome]

st.sidebar.divider()
st.sidebar.header("2. Penalidades (Execução)")
aplicar_multa_523 = st.sidebar.checkbox("Aplicar Multa de 10% (Art. 523)?", value=False)
aplicar_hon_523 = st.sidebar.checkbox("Aplicar Honorários de 10%?", value=False)

# --- ESTADO DA APLICAÇÃO (MEMÓRIA) ---
if 'total_indenizacao' not in st.session_state: st.session_state.total_indenizacao = 0.0
if 'total_honorarios' not in st.session_state: st.session_state.total_honorarios = 0.0
if 'total_pensao' not in st.session_state: st.session_state.total_pensao = 0.0
if 'df_indenizacao' not in st.session_state: st.session_state.df_indenizacao = pd.DataFrame()
if 'df_honorarios' not in st.session_state: st.session_state.df_honorarios = pd.DataFrame()
if 'df_pensao_input' not in st.session_state: st.session_state.df_pensao_input = pd.DataFrame()
if 'df_pensao_final' not in st.session_state: st.session_state.df_pensao_final = pd.DataFrame()

tab1, tab2, tab3, tab4 = st.tabs(["🏢 1. Indenização Cível", "⚖️ 2. Honorários", "👶 3. Pensão Alimentícia", "📊 4. RESUMO E PDF"])

# ==============================================================================
# ABA 1: INDENIZAÇÃO CÍVEL
# ==============================================================================
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
    
    # --- SELETOR DE JUROS (AQUI ESTÁ A MUDANÇA) ---
    st.write("---")
    st.write("**Regime de Atualização e Juros:**")
    tipo_juros = st.radio(
        "Escolha o critério:",
        [f"Correção ({indice_padrao_nome}) + Juros de 1% a.m.", "Taxa SELIC (Substitui Correção e Juros)"],
        horizontal=True
    )
    
    usar_selic = "Taxa SELIC" in tipo_juros
    
    data_citacao_ind = None
    if not usar_selic:
        data_citacao_ind = st.date_input("Data da Citação (Para início dos Juros de 1%)", value=date(2025, 2, 25))
    else:
        st.info("ℹ️ Com a Taxa SELIC, a correção e os juros são unificados em uma única taxa. Juros de 1% foram desativados.")

    if st.button("Calcular Indenização", type="primary"):
        lista_ind = []
        
        # Define qual código usar: O padrão escolhido ou a SELIC (4390)
        codigo_final = 4390 if usar_selic else codigo_indice_padrao
        
        if metodo_calculo == "Ciclo Mensal":
            temp_date = inicio_atraso
            while temp_date < fim_atraso:
                prox_mes = temp_date + relativedelta(months=1)
                data_vencimento = prox_mes - timedelta(days=1)
                fator_pro_rata = 1.0
                if data_vencimento > fim_atraso:
                    dias_no_mes = (data_vencimento - temp_date).days + 1
                    dias_pro_rata = (fim_atraso - temp_date).days + 1
                    fator_pro_rata = dias_pro_rata / dias_no_mes
                    data_vencimento = fim_atraso
                
                valor_base_mes = valor_mensal_cheio * fator_pro_rata
                
                # Busca fator (SELIC ou Índice Padrão)
                fator_att = buscar_fator_bcb(codigo_final, data_vencimento, data_calculo)
                
                if usar_selic:
                    val_corr = valor_base_mes * fator_att
                    val_juros = 0.0
                    txt_juros = "Incluso (SELIC)"
                    txt_fator = f"SELIC {fator_att:.4f}"
                else:
                    val_corr = valor_base_mes * fator_att
                    data_inicio_juros = data_citacao_ind if data_vencimento < data_citacao_ind else data_vencimento
                    dias_juros = (data_calculo - data_inicio_juros).days
                    val_juros = val_corr * (0.01/30 * dias_juros) if dias_juros > 0 else 0.0
                    txt_juros = f"R$ {val_juros:,.2f}"
                    txt_fator = f"{indice_padrao_nome} {fator_att:.4f}"
                
                lista_ind.append({"Vencimento": data_vencimento.strftime("%d/%m/%Y"), "Valor Orig.": f"R$ {valor_base_mes:,.2f}", "Fator": txt_fator, "V. Corrigido": f"R$ {val_corr:,.2f}", "Juros (R$)": txt_juros, "TOTAL": f"R$ {val_corr + val_juros:,.2f}", "_num": val_corr + val_juros})
                temp_date = prox_mes.replace(day=1)
        else:
            curr_date = inicio_atraso.replace(day=1)
            end_date_ref = fim_atraso.replace(day=1)
            meses_list = []
            while curr_date <= end_date_ref:
                meses_list.append(curr_date)
                curr_date = curr_date + relativedelta(months=1)
            
            for i, mes_ref in enumerate(meses_list):
                ultimo_dia_mes = mes_ref.replace(day=calendar.monthrange(mes_ref.year, mes_ref.month)[1])
                inicio_efetivo = inicio_atraso if mes_ref.year == inicio_atraso.year and mes_ref.month == inicio_atraso.month else mes_ref
                fim_efetivo = fim_atraso if mes_ref.year == fim_atraso.year and mes_ref.month == fim_atraso.month else ultimo_dia_mes
                
                dias_no_mes = calendar.monthrange(mes_ref.year, mes_ref.month)[1]
                dias_corridos = (fim_efetivo - inicio_efetivo).days + 1
                eh_mes_cheio = (inicio_efetivo.day == 1 and fim_efetivo.day == ultimo_dia_mes.day)
                
                if eh_mes_cheio: valor_base_mes = valor_mensal_cheio
                else: valor_base_mes = (valor_mensal_cheio / dias_no_mes) * dias_corridos
                
                data_vencimento = fim_efetivo
                
                fator_att = buscar_fator_bcb(codigo_final, data_vencimento, data_calculo)
                
                if usar_selic:
                    val_corr = valor_base_mes * fator_att
                    val_juros = 0.0
                    txt_juros = "Incluso (SELIC)"
                    txt_fator = f"SELIC {fator_att:.4f}"
                else:
                    val_corr = valor_base_mes * fator_att
                    data_inicio_juros = data_citacao_ind if data_vencimento < data_citacao_ind else data_vencimento
                    dias_juros = (data_calculo - data_inicio_juros).days
                    val_juros = val_corr * (0.01/30 * dias_juros) if dias_juros > 0 else 0.0
                    txt_juros = f"R$ {val_juros:,.2f}"
                    txt_fator = f"{indice_padrao_nome} {fator_att:.4f}"
                
                lista_ind.append({"Vencimento": data_vencimento.strftime("%d/%m/%Y"), "Valor Orig.": f"R$ {valor_base_mes:,.2f}", "Fator": txt_fator, "V. Corrigido": f"R$ {val_corr:,.2f}", "Juros (R$)": txt_juros, "TOTAL": f"R$ {val_corr + val_juros:,.2f}", "_num": val_corr + val_juros})

        if lista_ind:
            df = pd.DataFrame(lista_ind)
            st.session_state.df_indenizacao = df
            st.session_state.total_indenizacao = df["_num"].sum()
            st.success(f"Total Indenização: R$ {st.session_state.total_indenizacao:,.2f}")
            st.dataframe(df.drop(columns=["_num"]), use_container_width=True)

# ==============================================================================
# ABA 2: HONORÁRIOS
# ==============================================================================
with tab2:
    st.subheader("Cálculo de Honorários")
    col_h1, col_h2 = st.columns(2)
    valor_honorarios = col_h1.number_input("Valor Arbitrado (R$)", value=1500.00)
    col_d1, col_d2 = st.columns(2)
    data_base_corr = col_d1.date_input("Correção desde:", value=date(2024, 12, 3))
    data_base_juros = col_d2.date_input("Juros desde:", value=date(2025, 11, 10))
    
    # Opção SELIC também para honorários
    tipo_juros_h = st.radio("Regime:", [f"Padrão ({indice_padrao_nome} + 1%)", "Taxa SELIC"], key="reg_h")
    usar_selic_h = "SELIC" in tipo_juros_h
    
    if st.button("Calcular Honorários"):
        cod_h = 4390 if usar_selic_h else codigo_indice_padrao
        fator_h = buscar_fator_bcb(cod_h, data_base_corr, data_calculo)
        
        if usar_selic_h:
             val_h_corr = valor_honorarios * fator_h
             val_h_juros = 0.0
             txt_juros_h = "Incluso (SELIC)"
        else:
             val_h_corr = valor_honorarios * fator_h
             dias_h = (data_calculo - data_base_juros).days
             val_h_juros = val_h_corr * (0.01/30 * dias_h) if dias_h > 0 else 0.0
             txt_juros_h = f"R$ {val_h_juros:,.2f}"
            
        total_h = val_h_corr + val_h_juros
        res_hon = [{"Descrição": "Honorários", "Valor Orig.": f"R$ {valor_honorarios:,.2f}", "Juros": txt_juros_h, "TOTAL": f"R$ {total_h:,.2f}", "_num": total_h}]
        st.session_state.df_honorarios = pd.DataFrame(res_hon)
        st.session_state.total_honorarios = total_h
        st.success(f"Total Honorários: R$ {total_h:,.2f}")

# ==============================================================================
# ABA 3: PENSÃO ALIMENTÍCIA
# ==============================================================================
with tab3:
    st.subheader("👶 Pensão Alimentícia")
    c_pen1, c_pen2 = st.columns(2)
    v_pensao = c_pen1.number_input("Valor da Parcela (R$)", value=1000.00)
    d_venc = c_pen2.number_input("Dia do Vencimento", value=10, min_value=1, max_value=31)
    c_pen3, c_pen4 = st.columns(2)
    ini_pen = c_pen3.date_input("Data Início", value=date(2023, 1, 1))
    fim_pen = c_pen4.date_input("Data Fim", value=date.today())
    
    usar_juros_pen = st.checkbox("Aplicar Juros de Mora (1% a.m.)?", value=True, key="ck_juros_pen")
    
    if st.button("1. Gerar Tabela para Edição"):
        lista_datas = []
        dt = ini_pen.replace(day=d_venc) if d_venc <= 28 else ini_pen 
        if dt < ini_pen: dt += relativedelta(months=1)
        while dt <= fim_pen:
            lista_datas.append({"Vencimento": dt, "Valor Devido (R$)": float(v_pensao), "Valor Pago (R$)": 0.00})
            dt += relativedelta(months=1)
        st.session_state.df_pensao_input = pd.DataFrame(lista_datas)

    if not st.session_state.df_pensao_input.empty:
        st.write("👇 **Edite abaixo os valores pagos:**")
        tabela_editada = st.data_editor(st.session_state.df_pensao_input, num_rows="dynamic", hide_index=True)
        
        if st.button("2. Calcular Saldo Final", type="primary"):
            resultados_p = []
            for i, row in tabela_editada.iterrows():
                venc = pd.to_datetime(row["Vencimento"]).date()
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
                resultados_p.append({"Vencimento": venc.strftime("%d/%m/%Y"), "Devido Orig.": f"R$ {v_orig:,.2f}", "Pago": f"R$ {v_pago:,.2f}", "Devido Atual.": f"R$ {v_corr:,.2f}", "Juros": f"R$ {juros:,.2f}", "SALDO DEVEDOR": f"R$ {saldo_mes:,.2f}", "_num": saldo_mes})
                
            st.session_state.df_pensao_final = pd.DataFrame(resultados_p)
            st.session_state.total_pensao = st.session_state.df_pensao_final["_num"].sum()
            st.success(f"Saldo Devedor: R$ {st.session_state.total_pensao:,.2f}")

# ==============================================================================
# ABA 4: RESUMO E PDF
# ==============================================================================
with tab4:
    st.subheader("Resumo Global e Relatório")
    t1 = st.session_state.total_indenizacao
    t2 = st.session_state.total_honorarios
    t3 = st.session_state.total_pensao
    
    if not (t1 > 0 or t2 > 0 or t3 > 0):
        st.info("Realize cálculos nas abas anteriores para ver o resultado.")
    else:
        subtotal = t1 + t2 + t3
        multa = subtotal * 0.10 if aplicar_multa_523 else 0.0
        hon_exec = subtotal * 0.10 if aplicar_hon_523 else 0.0
        final = subtotal + multa + hon_exec
        
        st.write("### Discriminativo do Débito")
        if t1 > 0: st.write(f"🔹 **Indenização Cível:** R$ {t1:,.2f}")
        if t2 > 0: st.write(f"🔹 **Honorários Sucumbenciais:** R$ {t2:,.2f}")
        if t3 > 0: st.write(f"🔹 **Pensão Alimentícia:** R$ {t3:,.2f}")
        st.markdown("---")
        st.write(f"**Subtotal:** R$ {subtotal:,.2f}")
        if aplicar_multa_523: st.write(f"+ Multa 10% (Art. 523): R$ {multa:,.2f}")
        if aplicar_hon_523: st.write(f"+ Honorários 10% (Art. 523): R$ {hon_exec:,.2f}")
        st.success(f"TOTAL FINAL DA EXECUÇÃO: R$ {final:,.2f}")
        
        totais_pdf = {'indenizacao': t1, 'honorarios': t2, 'pensao': t3, 'multa': multa, 'hon_exec': hon_exec, 'final': final}
        config_pdf = {'multa_523': aplicar_multa_523, 'hon_523': aplicar_hon_523}
        pdf_bytes = gerar_pdf_relatorio(st.session_state.df_indenizacao, st.session_state.df_honorarios, st.session_state.df_pensao_final, totais_pdf, config_pdf)
        st.download_button(label="📄 BAIXAR RELATÓRIO PDF COMPLETO", data=pdf_bytes, file_name="calculo_judicial.pdf", mime="application/pdf")

    if st.button("Limpar Todos os Cálculos"):
        for key in st.session_state.keys(): del st.session_state[key]
        st.rerun()
