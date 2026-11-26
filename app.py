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
            fecha_servicio = st.text_input("Fecha Servicio (YYYY-MM-DD)", value=hoy_str).strip()
            proximo_servicio_manual = st.text_input(
                "Próximo Servicio (opcional, auto si queda vacío)",
                value="",
                placeholder="YYYY-MM-DD (se calcula automáticamente)",
            ).strip()

        with c3:
            no_eco = st.text_input(
                "No. Económico",
                value=eco_inicial,
                placeholder="Ej. 093, SB-014, U-97",
            ).strip()
            kilometraje = st.text_input("Kilometraje", placeholder="Ej. 85000").strip()
            estado = st.selectbox(
                "Estado",
                ["Programado", "En proceso", "Completado", "Pendiente", "Vencido"],
                index=0,
            )
            monto = st.number_input("Monto ($)", min_value=0.0, value=0.0, step=50.0, format="%.2f")

        observaciones = st.text_area("Observaciones", height=75, placeholder="Detalles del diagnóstico o servicio...").strip()

        enviar = st.form_submit_button("Guardar registro preventivo", type="primary")

        if enviar:
            if not cliente or not vehiculo:
                st.error("Captura al menos **Cliente** y **Vehículo / Unidad**.")
            else:
                df_base = normalizar_df_sp(cargar_servicios_prev(FILE_SERV_PREV))
                folio_final = folio_prev if folio_prev else (siguiente_folio_sp(df_base) or f"SP-{len(df_base) + 1:02d}")
                prox_final = proximo_servicio_manual
                if not prox_final:
                    prox_final = calcular_proximo_servicio(fecha_servicio, int(meses_intervalo))

                fila_dict = {col: "" for col in COLS_SP}
                fila_dict.update({
                    "Folio_Prev": folio_final,
                    "Cliente": cliente,
                    "Telefono": telefono,
                    "Vehiculo": vehiculo,
                    "Anio": anio,
                    "No_Economico": str(no_eco),
                    "Refrigerante": refrigerante,
                    "Servicio_Preventivo": servicio_prev,
                    "Fecha_Servicio": fecha_servicio,
                    "Meses_Intervalo": int(meses_intervalo),
                    "Proximo_Servicio": prox_final,
                    "Kilometraje": kilometraje,
                    "Estado": estado,
                    "Monto": float(monto),
                    "Observaciones": observaciones,
                })
                nueva_fila = pd.DataFrame([fila_dict], columns=COLS_SP)
                df_nuevo = pd.concat([df_base, nueva_fila], ignore_index=True)

                if guardar_servicios_prev(df_nuevo, FILE_SERV_PREV):
                    st.session_state["df_serv_prev"] = cargar_servicios_prev(FILE_SERV_PREV)
                    st.success(f"Guardado **{folio_final}** — No. Económico: `{str(no_eco)}`")
                    st.rerun()

# ==========================================
# PESTAÑA 2: TICKET DE VENTA
# ==========================================
with tab_ticket:
    st.subheader("Emitir Ticket de Venta")
    df_vt_actual = normalizar_df_vt(cargar_ventas())
    folio_sugerido = siguiente_folio_vt(df_vt_actual)

    with st.form("form_ticket_venta", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            folio_venta = st.text_input("Folio", value=folio_sugerido)
            fecha_venta = st.date_input("Fecha", value=dt.date.today())
            cliente_vt = st.text_input("Cliente", placeholder="Ej. Transportes del Pacífico")
            telefono_vt = st.text_input("Teléfono", placeholder="Ej. 6121234567")
            vehiculo_vt = st.text_input("Unidad / Vehículo", placeholder="Ej. Freightliner M2")
            no_eco_vt = st.text_input("No. Económico", placeholder="Ej. 005")
        with c2:
            concepto_vt = st.text_input("Concepto", placeholder="Ej. Carga refrigerante y revisión")
            refrigerante_vt = st.text_input("Refrigerante", placeholder="Ej. R134a / R404A")
            cantidad_vt = st.number_input("Cantidad", min_value=1, max_value=999, value=1, step=1)
            precio_unit_vt = st.number_input("Precio Unitario ($)", min_value=0.0, value=0.0, step=50.0, format="%.2f")
            metodo_pago = st.selectbox("Método de Pago", ["Efectivo", "Transferencia", "Tarjeta", "Crédito"])
            estado_pago = st.selectbox("Estado", ["Pagado", "Pendiente", "Abono"])

        obs_vt = st.text_input("Observaciones", placeholder="Opcional")
        emitir = st.form_submit_button("Generar ticket de venta", type="primary")

            if emitir:
                df_vt_fresh = normalizar_df_vt(cargar_ventas())
                folio_limpio = folio_venta.strip() or siguiente_folio_vt(df_vt_fresh)
                total_calc = round(int(cantidad_vt) * float(precio_unit_vt), 2)
                registro_vt = {
                    "Folio_Venta": folio_limpio,
                    "Folio_Referencia": "",
                    "Fecha_Venta": fecha_venta.isoformat(),
                    "Cliente": cliente_vt.strip(),
                    "Telefono": telefono_vt.strip(),
                    "Vehiculo": vehiculo_vt.strip(),
                    "No_Economico": str(no_eco_vt).strip(),
                    "Concepto": concepto_vt.strip(),
                    "Refrigerante": refrigerante_vt.strip(),
                    "Cantidad": int(cantidad_vt),
                    "Precio_Unitario": float(precio_unit_vt),
                    "Total": float(total_calc),
                    "Metodo_Pago": metodo_pago,
                    "Estado_Pago": estado_pago,
                    "Observaciones": obs_vt.strip(),
                }
                "Vehiculo": vehiculo_vt.strip(),
                "No_Economico": str(no_eco_vt).strip(),
                "Concepto": concepto_vt.strip(),
                "Refrigerante": refrigerante_vt.strip(),
                "Cantidad": int(cantidad_vt),
