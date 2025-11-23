import streamlit as st
import pandas as pd
import requests
import calendar
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

# --- CONFIGURAÇÃO VISUAL ---
st.set_page_config(page_title="CalcJus Pro Multi", layout="wide")

st.title("⚖️ CalcJus PRO - Central de Cálculos Judiciais")
st.markdown("Cálculos de **Indenizações**, **Honorários** e **Pensão Alimentícia** com atualização oficial.")

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
                fator *= (1 + float(item['valor'])/100)
            return fator
    except:
        pass
    return 1.0

# --- MENU LATERAL ---
st.sidebar.header("1. Parâmetros Gerais")
data_calculo = st.sidebar.date_input("Data do Cálculo (Atualização)", value=date.today())

mapa_indices = {"INPC (IBGE)": 188, "IGP-M (FGV)": 189, "INCC-DI": 192, "IPCA-E": 10764, "IPCA": 433}
indice_nome = st.sidebar.selectbox("Índice de Correção", list(mapa_indices.keys()))
codigo_indice = mapa_indices[indice_nome]

st.sidebar.divider()
st.sidebar.header("2. Penalidades")
aplicar_multa_523 = st.sidebar.checkbox("Aplicar Multa de 10% (Art. 523)?", value=False)
aplicar_hon_523 = st.sidebar.checkbox("Aplicar Honorários de 10%?", value=False)

# --- MEMÓRIA DO APP ---
if 'total_indenizacao' not in st.session_state: st.session_state.total_indenizacao = 0.0
if 'total_honorarios' not in st.session_state: st.session_state.total_honorarios = 0.0
if 'total_pensao' not in st.session_state: st.session_state.total_pensao = 0.0
if 'df_indenizacao' not in st.session_state: st.session_state.df_indenizacao = pd.DataFrame()
if 'df_honorarios' not in st.session_state: st.session_state.df_honorarios = pd.DataFrame()
if 'df_pensao_input' not in st.session_state: st.session_state.df_pensao_input = pd.DataFrame()

tab1, tab2, tab3, tab4 = st.tabs([
    "🏢 1. Indenização Cível", 
    "⚖️ 2. Honorários", 
    "👶 3. Pensão Alimentícia", 
    "📊 4. RESUMO GERAL"
])

# ==============================================================================
# ABA 1: INDENIZAÇÃO (CÍVEL/CONSTRUTORA) - COM PRO-RATA DIE
# ==============================================================================
with tab1:
    st.subheader("Cálculo de Lucros Cessantes / Indenização")
    
    c1, c2, c3 = st.columns(3)
    valor_contrato = c1.number_input("Valor Base (Contrato/Aluguel)", value=318316.50, step=1000.00)
    perc_indenizacao = c2.number_input("% Mensal (ou deixe 100% para valor fixo)", value=0.5, step=0.1)
    valor_mensal_cheio = valor_contrato * (perc_indenizacao / 100)
    c3.metric("Valor Mensal Cheio", f"R$ {valor_mensal_cheio:,.2f}")
    
    st.write("---")
    c4, c5 = st.columns(2)
    inicio_atraso = c4.date_input("Início da Mora", value=date(2024, 7, 1))
    fim_atraso = c5.date_input("Fim da Mora", value=date(2024, 10, 16))
    
    c6, c7 = st.columns(2)
    data_citacao_ind = c6.date_input("Data da Citação (Para Juros)", value=date(2025, 2, 25))
    metodo_calculo = c7.radio("Método de Contagem:", ["Ciclo Mensal (Data a Data)", "Mês Civil (Pro-Rata Die)"], index=1, help="Mês Civil calcula os dias exatos de cada mês (ex: 16/31 dias em Outubro).")

    if st.button("Calcular Indenização", type="primary"):
        lista_ind = []
        progresso = st.progress(0, text="Calculando...")
        
        if metodo_calculo == "Ciclo Mensal (Data a Data)":
            # Lógica Antiga (Data a Data)
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
                
                # Correção e Juros
                fator_corr = buscar_fator_bcb(codigo_indice, data_vencimento, data_calculo)
                val_corr = valor_base_mes * fator_corr
                data_inicio_juros = data_citacao_ind if data_vencimento < data_citacao_ind else data_vencimento
                dias_juros = (data_calculo - data_inicio_juros).days
                val_juros = val_corr * (0.01/30 * dias_juros) if dias_juros > 0 else 0.0
                
                lista_ind.append({
                    "Período/Venc.": data_vencimento.strftime("%d/%m/%Y"),
                    "Dias": "30" if fator_pro_rata == 1 else f"{int(dias_pro_rata)}/{int(dias_no_mes)}",
                    "Valor Orig.": f"R$ {valor_base_mes:,.2f}",
                    "V. Atualizado": f"R$ {val_corr:,.2f}",
                    "Juros": f"R$ {val_juros:,.2f}",
                    "TOTAL": f"R$ {val_corr + val_juros:,.2f}",
                    "_num": val_corr + val_juros
                })
                temp_date = prox_mes.replace(day=1) # Avança
        
        else:
            # Lógica Nova (Mês Civil - Pro Rata Die Exato)
            # Itera mês a mês do calendário (Julho, Agosto, Setembro...)
            curr_date = inicio_atraso.replace(day=1)
            end_date_ref = fim_atraso.replace(day=1)
            
            # Lista de meses envolvidos
            meses_list = []
            while curr_date <= end_date_ref:
                meses_list.append(curr_date)
                curr_date = curr_date + relativedelta(months=1)
            
            for i, mes_ref in enumerate(meses_list):
                # Define o último dia deste mês
                ultimo_dia_mes = mes_ref.replace(day=calendar.monthrange(mes_ref.year, mes_ref.month)[1])
                
                # Define início e fim efetivos dentro deste mês
                inicio_efetivo = inicio_atraso if mes_ref.year == inicio_atraso.year and mes_ref.month == inicio_atraso.month else mes_ref
                fim_efetivo = fim_atraso if mes_ref.year == fim_atraso.year and mes_ref.month == fim_atraso.month else ultimo_dia_mes
                
                # Calcula dias
                dias_no_mes = calendar.monthrange(mes_ref.year, mes_ref.month)[1]
                dias_corridos = (fim_efetivo - inicio_efetivo).days + 1
                
                # Se cobriu o mês todo, valor cheio. Se não, pro-rata.
                # Nota: Se o início for dia 1 e fim for último dia, é cheio.
                eh_mes_cheio = (inicio_efetivo.day == 1 and fim_efetivo.day == ultimo_dia_mes.day)
                
                if eh_mes_cheio:
                    valor_base_mes = valor_mensal_cheio
                    txt_dias = f"{dias_no_mes} (Cheio)"
                else:
                    valor_base_mes = (valor_mensal_cheio / dias_no_mes) * dias_corridos
                    txt_dias = f"{dias_corridos}/{dias_no_mes}"
                
                # Vencimento é o último dia considerado (regra geral de indenização mensal)
                data_vencimento = fim_efetivo
                
                # Correção e Juros
                fator_corr = buscar_fator_bcb(codigo_indice, data_vencimento, data_calculo)
                val_corr = valor_base_mes * fator_corr
                
                data_inicio_juros = data_citacao_ind if data_vencimento < data_citacao_ind else data_vencimento
                dias_juros = (data_calculo - data_inicio_juros).days
                val_juros = val_corr * (0.01/30 * dias_juros) if dias_juros > 0 else 0.0
                
                lista_ind.append({
                    "Mês Ref.": mes_ref.strftime("%m/%Y"),
                    "Dias Proporc.": txt_dias,
                    "Valor Orig.": f"R$ {valor_base_mes:,.2f}",
                    "V. Atualizado": f"R$ {val_corr:,.2f}",
                    "Juros": f"R$ {val_juros:,.2f}",
                    "TOTAL": f"R$ {val_corr + val_juros:,.2f}",
                    "_num": val_corr + val_juros
                })
                progresso.progress((i + 1) / len(meses_list))

        progresso.empty()
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
    
    if st.button("Calcular Honorários"):
        fator_h = buscar_fator_bcb(codigo_indice, data_base_corr, data_calculo)
        val_h_corr = valor_honorarios * fator_h
        dias_h = (data_calculo - data_base_juros).days
        val_h_juros = val_h_corr * (0.01/30 * dias_h) if dias_h > 0 else 0.0
        total_h = val_h_corr + val_h_juros
        
        res_hon = [{"Descrição": "Honorários", "Valor Orig.": f"R$ {valor_honorarios:,.2f}", "TOTAL": f"R$ {total_h:,.2f}", "_num": total_h}]
        st.session_state.df_honorarios = pd.DataFrame(res_hon)
        st.session_state.total_honorarios = total_h
        st.success(f"Total Honorários: R$ {total_h:,.2f}")

# ==============================================================================
# ABA 3: PENSÃO ALIMENTÍCIA (COM PAGAMENTOS PARCIAIS)
# ==============================================================================
with tab3:
    st.subheader("👶 Pensão Alimentícia com Abatimentos")
    st.info("1. Gere a tabela. 2. Edite a coluna 'Valor Pago'. 3. Clique em Calcular Saldo.")
    
    c_pen1, c_pen2 = st.columns(2)
    v_pensao = c_pen1.number_input("Valor da Parcela (R$)", value=1000.00)
    d_venc = c_pen2.number_input("Dia do Vencimento", value=10, min_value=1, max_value=31)
    
    c_pen3, c_pen4 = st.columns(2)
    ini_pen = c_pen3.date_input("Data Início", value=date(2023, 1, 1))
    fim_pen = c_pen4.date_input("Data Fim", value=date.today())
    
    if st.button("1. Gerar Tabela para Edição"):
        lista_datas = []
        dt = ini_pen.replace(day=d_venc) if d_venc <= 28 else ini_pen 
        if dt < ini_pen: dt += relativedelta(months=1)
        
        while dt <= fim_pen:
            lista_datas.append({
                "Vencimento": dt,
                "Descrição": f"Pensão {dt.strftime('%m/%Y')}",
                "Valor Devido (R$)": float(v_pensao),
                "Valor Pago (R$)": 0.00
            })
            dt += relativedelta(months=1)
            
        st.session_state.df_pensao_input = pd.DataFrame(lista_datas)

    if not st.session_state.df_pensao_input.empty:
        st.write("👇 **Edite abaixo os valores que foram pagos (parcialmente ou total):**")
        tabela_editada = st.data_editor(
            st.session_state.df_pensao_input,
            column_config={
                "Vencimento": st.column_config.DateColumn("Vencimento", format="DD/MM/YYYY"),
                "Valor Devido (R$)": st.column_config.NumberColumn("Devido", format="R$ %.2f"),
                "Valor Pago (R$)": st.column_config.NumberColumn("Pago (Abater)", format="R$ %.2f"),
            },
            hide_index=True,
            num_rows="dynamic"
        )
        
        if st.button("2. Calcular Saldo Devedor Final", type="primary"):
            resultados_p = []
            progresso_p = st.progress(0, text="Calculando saldo devedor...")
            total_rows = len(tabela_editada)
            
            for i, row in tabela_editada.iterrows():
                progresso_p.progress((i + 1) / total_rows)
                
                venc = pd.to_datetime(row["Vencimento"]).date()
                v_orig = row["Valor Devido (R$)"]
                v_pago = row["Valor Pago (R$)"]
                
                fator = buscar_fator_bcb(codigo_indice, venc, data_calculo)
                v_corr = v_orig * fator
                
                dias = (data_calculo - venc).days
                juros = v_corr * (0.01/30 * dias) if dias > 0 else 0.0
                
                total_bruto = v_corr + juros
                saldo_mes = total_bruto - v_pago
                
                resultados_p.append({
                    "Vencimento": venc.strftime("%d/%m/%Y"),
                    "Devido Orig.": f"R$ {v_orig:,.2f}",
                    "Pago": f"R$ {v_pago:,.2f}",
                    "Devido Atual.": f"R$ {v_corr:,.2f}",
                    "Juros": f"R$ {juros:,.2f}",
                    "SALDO DEVEDOR": f"R$ {saldo_mes:,.2f}",
                    "_num": saldo_mes
                })
                
            progresso_p.empty()
            df_final_p = pd.DataFrame(resultados_p)
            st.session_state.total_pensao = df_final_p["_num"].sum()
            
            st.divider()
            st.success(f"Saldo Devedor de Pensão: R$ {st.session_state.total_pensao:,.2f}")
            st.dataframe(df_final_p.drop(columns=["_num"]), use_container_width=True)

# ==============================================================================
# ABA 4: RESUMO GERAL
# ==============================================================================
with tab4:
    st.subheader("Resumo Global da Execução")
    
    t1 = st.session_state.total_indenizacao
    t2 = st.session_state.total_honorarios
    t3 = st.session_state.total_pensao
    subtotal = t1 + t2 + t3
    
    multa = subtotal * 0.10 if aplicar_multa_523 else 0.0
    hon_exec = subtotal * 0.10 if aplicar_hon_523 else 0.0
    final = subtotal + multa + hon_exec
    
    c_res1, c_res2 = st.columns(2)
    with c_res1:
        st.write(f"🔹 Indenização Cível: R$ {t1:,.2f}")
        st.write(f"🔹 Honorários Sucumbenciais: R$ {t2:,.2f}")
        st.write(f"🔹 Pensão Alimentícia (Saldo): R$ {t3:,.2f}")
        st.markdown("---")
        if aplicar_multa_523: st.write(f"+ Multa 10%: R$ {multa:,.2f}")
        if aplicar_hon_523: st.write(f"+ Honorários 10%: R$ {hon_exec:,.2f}")
        
    with c_res2:
        st.metric("TOTAL DA EXECUÇÃO", f"R$ {final:,.2f}")
    
    if st.button("Limpar Tudo"):
        for key in st.session_state.keys():
            del st.session_state[key]
        st.rerun()
