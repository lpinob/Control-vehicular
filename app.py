import streamlit as st
from supabase import create_client, Client
import easyocr
import numpy as np
from PIL import Image
import io
import pandas as pd
import matplotlib.pyplot as plt

# Configuración inicial de la página
st.set_page_config(
    page_title="Control Vehicular ACAPOMIL",
    layout="wide"
)

# Cargar credenciales desde los secretos de Streamlit
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
except Exception:
    st.error("No se encontraron las credenciales de Supabase en secrets.toml.")
    st.stop()

# Inicializar cliente de Supabase
@st.cache_resource
def init_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = init_supabase()

# Inicializar lector OCR en caché
@st.cache_resource
def init_ocr():
    return easyocr.Reader(['es', 'en'], gpu=False)

reader = init_ocr()

# --- CONTROL DE ESTADO Y SESIÓN ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'user_role' not in st.session_state:
    st.session_state.user_role = "Guardia (Terreno)"

# Barra lateral para selección de rol (Simulación de Autenticación)
st.sidebar.title("Panel de Control")
st.sidebar.write("Seleccione el perfil de acceso:")
rol_seleccionado = st.sidebar.selectbox("Rol de Usuario", ["Guardia (Terreno)", "Administrador (Puesto de Mando)"])
st.session_state.user_role = rol_seleccionado

st.sidebar.divider()
st.sidebar.info(f"Perfil activo: **{st.session_state.user_role}**")


# --- VISTA 1: MÓDULO MÓVIL / GARITA (GUARDIA) ---
def vista_guardia():
    st.title("Módulo de Control de Acceso - Garita")
    st.write("Captura rápida de patentes, reconocimiento OCR y validación vehicular.")

    col1, col2 = st.columns([1, 1])

    patente_detectada = ""

    with col1:
        st.subheader("1. Captura de Evidencia Visual")
        imagen_capturada = st.camera_input("Fotografiar vehículo / patente")

        bytes_imagen = None
        if imagen_capturada is not None:
            bytes_imagen = imagen_capturada.getvalue()
            imagen_pil = Image.open(io.BytesIO(bytes_imagen))
            imagen_np = np.array(imagen_pil)
            
            with st.spinner("Procesando OCR..."):
                resultados = reader.readtext(imagen_np)
                
            if resultados:
                patente_detectada = max(resultados, key=lambda x: x[2])[1].upper().replace(" ", "").replace("-", "")
                st.success(f"Patente detectada: **{patente_detectada}**")
            else:
                st.warning("No se reconoció texto automáticamente. Ingrese la patente de forma manual.")

    with col2:
        st.subheader("2. Verificación y Registro")
        patente_busqueda = st.text_input("Patente a verificar:", value=patente_detectada)

        if patente_busqueda.strip():
            patente_limpia = patente_busqueda.strip().upper()
            
            # Consultar vehículo en Supabase
            response = supabase.table("vehiculos").select("*").eq("patente", patente_limpia).execute()
            
            if response.data:
                vehiculo = response.data[0]
                
                if vehiculo["autorizado"]:
                    st.success("ESTADO: VEHÍCULO AUTORIZADO")
                else:
                    st.error("ESTADO: DENEGADO / NO AUTORIZADO")
                
                st.write(f"**Propietario:** {vehiculo['propietario']}")
                st.write(f"**Unidad:** {vehiculo['unidad']}")
                st.write(f"**Vehículo:** {vehiculo['marca']} {vehiculo['modelo']} ({vehiculo['color']})")

                with st.form("form_garita"):
                    tipo_movimiento = st.selectbox("Movimiento:", ["ENTRADA", "SALIDA"])
                    btn_registrar = st.form_submit_button("Confirmar Registro de Acceso")

                    if btn_registrar:
                        imagen_url = ""
                        # Subir imagen a Supabase Storage si existe captura
                        if bytes_imagen is not None:
                            try:
                                nombre_archivo = f"acceso_{patente_limpia}_{np.random.randint(1000, 9999)}.jpg"
                                supabase.storage.from_("evidencias-garita").upload(nombre_archivo, bytes_imagen, file_options={"content-type": "image/jpeg"})
                                imagen_url = supabase.storage.from_("evidencias-garita").get_public_url(nombre_archivo)
                            except Exception as e:
                                st.warning(f"No se pudo subir la imagen al storage: {e}")

                        # Insertar registro
                        try:
                            supabase.table("registros_acceso").insert({
                                "patente": patente_limpia,
                                "movimiento": tipo_movimiento,
                                "imagen_url": imagen_url
                            }).execute()
                            st.success(f"¡{tipo_movimiento} registrada con éxito para {patente_limpia}!")
                        except Exception as e:
                            st.error(f"Error al registrar: {e}")
            else:
                st.warning(f"La patente **{patente_limpia}** no se encuentra registrada en la base de datos institucional.")


# --- VISTA 2: PUESTO DE MANDO / DASHBOARD (ADMINISTRADOR) ---
def vista_admin():
    st.title("Puesto de Mando - Dashboard Operativo")
    st.write("Panel de control gerencial, métricas de flujo e historial con evidencia fotográfica.")

    # Cargar registros desde Supabase
    try:
        data_registros = supabase.table("registros_acceso").select("*").order("id", desc=True).execute().data
    except Exception as e:
        st.error(f"Error al conectar con la base de datos: {e}")
        return

    if not data_registros:
        st.info("Aún no existen registros de acceso en el sistema.")
        return

    df = pd.DataFrame(data_registros)

    # Tarjetas de KPIs principales
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Accesos Registrados", len(df))
    with col2:
        entradas = len(df[df['movimiento'] == 'ENTRADA'])
        st.metric("Entradas Registradas", entradas)
    with col3:
        salidas = len(df[df['movimiento'] == 'SALIDA'])
        st.metric("Salidas Registradas", salidas)

    st.divider()

    # Gráfico de movimientos
    st.subheader("Distribución de Flujo Operativo")
    conteo_movimiento = df['movimiento'].value_counts()
    fig, ax = plt.subplots(figsize=(4, 2))
    conteo_movimiento.plot(kind='bar', ax=ax, color=['#1f77b4', '#ff7f0e'])
    ax.set_ylabel("Cantidad")
    st.pyplot(fig)

    st.divider()

    # Historial detallado con evidencia visual
    st.subheader("Auditoría de Accesos e Historial Fotográfico")
    
    filtro_patente = st.text_input("Filtrar por Patente específica:")
    if filtro_patente:
        df = df[df['patente'].str.contains(filtro_patente.upper())]

    for index, row in df.iterrows():
        with st.container():
            col_info, col_img = st.columns([2, 1])
            with col_info:
                st.write(f"**ID Registro:** {row['id']}")
                st.write(f"**Patente:** {row['patente']}")
                st.write(f"**Movimiento:** {row['movimiento']}")
                st.write(f"**Fecha y Hora (UTC):** {row['fecha_hora']}")
            with col_img:
                if row['imagen_url']:
                    st.image(row['imagen_url'], width=150, caption="Evidencia Garita")
                else:
                    st.info("Sin evidencia fotográfica")
            st.markdown("---")


# --- ENRUTAMIENTO DE VISTAS SEGÚN ROL ---
if st.session_state.user_role == "Guardia (Terreno)":
    vista_guardia()
else:
    vista_admin()