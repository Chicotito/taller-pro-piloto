import datetime as dt
import pandas as pd
import streamlit as st

from storage import (
    COLS_INV,
    COLS_SP,
    COLS_VT,
    FILE_INV,
    FILE_SERV_PREV,
    cargar_inventario,
    cargar_servicios_prev,
    cargar_ventas,
    guardar_inventario,
    guardar_servicios_prev,
    guardar_ventas,
    calcular_proximo_servicio,
    normalizar_df_inv,
    normalizar_df_sp,
    siguiente_folio_sp,
    siguiente_folio_vt,
    normalizar_df_vt,
)

st.set_page_config(page_title="Taller Olachea - App", layout="wide")
st.title("Taller Olachea — Sistema de Gestión")

ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "1234") if hasattr(st, "secrets") else "1234"

if "df_serv_prev" not in st.session_state:
    st.session_state["df_serv_prev"] = cargar_servicios_prev(FILE_SERV_PREV)
if "ticket_actual" not in st.session_state:
    st.session_state["ticket_actual"] = ""
if "folio_actual" not in st.session_state:
    st.session_state["folio_actual"] = "TICKET"


def generar_ticket(datos: dict) -> str:
    folio = datos.get("Folio_Venta") or "S/F"
    fecha = datos.get("Fecha_Venta") or dt.date.today().isoformat()
    cliente = datos.get("Cliente") or "Público general"
    tel = datos.get("Telefono") or "-"
    vehiculo = datos.get("Vehiculo") or "-"
    no_eco = datos.get("No_Economico") or "-"
    concepto = datos.get("Concepto") or "Servicio de refrigeración"
    ref = datos.get("Refrigerante") or "-"
    cant = int(datos.get("Cantidad", 1))
    p_unit = float(datos.get("Precio_Unitario", 0.0))
    total = float(datos.get("Total", cant * p_unit))
    pago = datos.get("Metodo_Pago") or "Efectivo"
    estado = datos.get("Estado_Pago") or "Pagado"
    obs = datos.get("Observaciones") or ""

    lineas = [
        "========================================",
        "      TALLER OLACHEA REFRIGERACION",
        "            TICKET DE VENTA",
        "========================================",
        f"Folio:         {folio}",
        f"Fecha:         {fecha}",
        f"Estado:        {estado}",
        "----------------------------------------",
        f"Cliente:       {cliente}",
        f"Telefono:      {tel}",
        f"Unidad:        {vehiculo}",
        f"No. Economico: {no_eco}",
        "----------------------------------------",
        f"Concepto:      {concepto}",
        f"Refrigerante:  {ref}",
        f"Cant x P.U.:   {cant} x ${p_unit:,.2f}",
        f"TOTAL:         ${total:,.2f}",
        f"Pago:          {pago}",
    ]
    if obs:
        lineas.append(f"Notas:         {obs}")
    lineas.extend([
        "========================================",
        "       Gracias por su preferencia",
        "========================================",
    ])
    return "\n".join(lineas)


def _es_duplicado_reciente_vt(df_existente: pd.DataFrame, nuevo: dict) -> bool:
    if df_existente.empty:
        return False
    ult = df_existente.iloc[-1]
    campos_comparar = [
        "Fecha_Venta",
        "Cliente",
        "Telefono",
        "Vehiculo",
        "No_Economico",
        "Concepto",
        "Refrigerante",
        "Cantidad",
        "Precio_Unitario",
        "Total",
        "Metodo_Pago",
        "Estado_Pago",
        "Observaciones",
    ]
    for campo in campos_comparar:
        val_ult = str(ult.get(campo, "") or "").strip()
        val_nuevo = str(nuevo.get(campo, "") or "").strip()
        if campo in {"Cantidad"}:
            try:
                if int(float(val_ult or 0)) != int(float(val_nuevo or 0)):
                    return False
            except ValueError:
                if val_ult != val_nuevo:
                    return False
        elif campo in {"Precio_Unitario", "Total"}:
            try:
                if round(float(val_ult or 0.0), 2) != round(float(val_nuevo or 0.0), 2):
                    return False
            except ValueError:
                if val_ult != val_nuevo:
                    return False
        else:
            if val_ult != val_nuevo:
                return False
    return True


tab_sp, tab_ticket, tab_reporte, tab_inv = st.tabs([
    "Servicios Preventivos",
    "Ticket de Venta",
    "Ventas (Día / Mensual)",
    "Inventario",
])

# ==========================================
# PESTAÑA 1: SERVICIOS PREVENTIVOS
# ==========================================
with tab_sp:
    st.caption(f"Archivo de datos: `{FILE_SERV_PREV}`")

    try:
        raw_sp = cargar_servicios_prev(FILE_SERV_PREV)
        df_actual = normalizar_df_sp(raw_sp)
    except Exception as e:
        st.warning(f"No se pudo leer el CSV previo ({e}). Se iniciará tabla vacía.")
        df_actual = pd.DataFrame(columns=COLS_SP)

    st.subheader("Registros actuales en CSV")
    st.dataframe(df_actual, use_container_width=True, hide_index=True)

    def _limpios(col_name: str) -> list[str]:
        if df_actual is None or df_actual.empty or col_name not in df_actual.columns:
            return []
        vals = [
            str(v).strip()
            for v in df_actual[col_name].tolist()
            if v is not None and str(v).strip() and str(v).strip().lower() != "nan"
        ]
        return sorted(set(vals))

    clientes_prev = _limpios("Cliente")
    vehiculos_prev = _limpios("Vehiculo")
    ecos_prev = _limpios("No_Economico")

    st.subheader("Nuevo registro de servicio preventivo")
    st.caption("Elige un dato existente para autocompletar o deja **(Nuevo / Escribir)** y escribe directo en el formulario.")

    s1, s2, s3 = st.columns(3)
    with s1:
        eco_sel = st.selectbox(
            "No. Económico registrado",
            options=["(Nuevo / Escribir)"] + ecos_prev,
            key="sp_eco_sel",
        )
    with s2:
        cli_sel = st.selectbox(
            "Cliente registrado",
            options=["(Nuevo / Escribir)"] + clientes_prev,
            key="sp_cli_sel",
        )
    with s3:
        veh_sel = st.selectbox(
            "Vehículo registrado",
            options=["(Nuevo / Escribir)"] + vehiculos_prev,
            key="sp_veh_sel",
        )

    eco_cli_def, eco_veh_def, eco_anio_def, eco_ref_def, eco_tel_def = "", "", "", "", ""
    if eco_sel != "(Nuevo / Escribir)" and not df_actual.empty and "No_Economico" in df_actual.columns:
        coincidencias = df_actual[df_actual["No_Economico"].astype(str).str.strip() == eco_sel]
        if not coincidencias.empty:
            ult = coincidencias.iloc[-1]
            eco_cli_def = str(ult.get("Cliente", "") or "").strip()
            eco_veh_def = str(ult.get("Vehiculo", "") or "").strip()
            eco_anio_def = str(ult.get("Anio", "") or "").strip()
            eco_ref_def = str(ult.get("Refrigerante", "") or "").strip()
            eco_tel_def = str(ult.get("Telefono", "") or "").strip()

    cli_inicial = "" if cli_sel == "(Nuevo / Escribir)" else cli_sel
    if not cli_inicial and eco_cli_def and eco_cli_def.lower() != "nan":
        cli_inicial = eco_cli_def

    veh_inicial = "" if veh_sel == "(Nuevo / Escribir)" else veh_sel
    if not veh_inicial and eco_veh_def and eco_veh_def.lower() != "nan":
        veh_inicial = eco_veh_def

    eco_inicial = "" if eco_sel == "(Nuevo / Escribir)" else eco_sel

    try:
        folio_sugerido = siguiente_folio_sp(df_actual) or f"SP-{len(df_actual) + 1:02d}"
    except Exception:
        folio_sugerido = f"SP-{len(df_actual) + 1:02d}"

    hoy_str = dt.date.today().isoformat()

    with st.form("form_detalle_sp", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)

        with c1:
            folio_prev = st.text_input("Folio Preventivo *", value=folio_sugerido).strip()
            cliente = st.text_input("Cliente *", value=cli_inicial).strip()
            telefono = st.text_input("Teléfono", value="" if eco_tel_def.lower() == "nan" else eco_tel_def).strip()
            refrigerante = st.text_input(
                "Refrigerante",
                value="" if eco_ref_def.lower() == "nan" else eco_ref_def,
                placeholder="Ej. R-134 / R134a / R404A",
            ).strip()
            meses_intervalo = st.number_input(
                "Meses de Intervalo",
                min_value=1,
                max_value=60,
                value=3,
                step=1,
            )

        with c2:
            vehiculo = st.text_input("Vehículo / Unidad *", value=veh_inicial).strip()
            anio = st.text_input(
                "Año",
                value="" if eco_anio_def.lower() == "nan" else eco_anio_def,
                placeholder="Ej. 2024",
            ).strip()
            servicio_prev = st.text_input(
                "Servicio Preventivo",
                placeholder="Ej. Carga completa de gas refrigerante",
            ).strip()
