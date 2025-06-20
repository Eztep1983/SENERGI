import traceback
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests
import logging
from datetime import datetime
import os

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Habilitar CORS para API calls desde el frontend

# Configuración de seguridad
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'tu-clave-secreta-aqui')

def validar_coordenadas(lat, lon):
    """Validar que las coordenadas estén dentro de Colombia y sean razonables"""
    try:
        lat_float = float(lat)
        lon_float = float(lon)
        
        # Límites aproximados de Colombia
        if not (-4.5 <= lat_float <= 13.5 and -82 <= lon_float <= -66):
            return False, "Las coordenadas están fuera de Colombia"
        
        return True, (lat_float, lon_float)
    except (ValueError, TypeError):
        return False, "Coordenadas inválidas"

def obtener_radiacion_solar(lat, lon):
    """Obtener datos de radiación solar desde NASA POWER API"""
    try:
        url = "https://power.larc.nasa.gov/api/temporal/climatology/point"
        params = {
            'parameters': 'ALLSKY_SFC_SW_DWN',
            'community': 'RE',
            'longitude': lon,
            'latitude': lat,
            'format': 'JSON'
        }
        
        logger.info(f"Consultando NASA POWER API para lat={lat}, lon={lon}")
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        
        # Verificar si la respuesta contiene los datos esperados
        if 'properties' not in data or 'parameter' not in data['properties']:
            logger.error(f"Respuesta inesperada de NASA POWER API: {data}")
            # Fallback con valores estimados para Colombia
            return 4.5, None
            
        radiacion_mensual = data['properties']['parameter']['ALLSKY_SFC_SW_DWN']
        
        # Calcular promedio anual
        valores_validos = [v for v in radiacion_mensual.values() if v is not None and v > 0]
        if not valores_validos:
            logger.error("No se encontraron valores válidos de radiación")
            return 4.5, None
            
        radiacion_anual = sum(valores_validos)
        radiacion_promedio_diaria = radiacion_anual / 12  # Promedio mensual convertido a diario
        
        logger.info(f"Radiación obtenida exitosamente: {radiacion_promedio_diaria:.2f} kWh/m²/día")
        return radiacion_promedio_diaria, radiacion_mensual
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error al obtener datos de NASA POWER: {e}")
        # Fallback con valores estimados para Colombia
        return 4.5, None
    except Exception as e:
        logger.error(f"Error procesando datos de radiación: {e}")
        return 4.5, None

def calcular_datos_solares(lat, lon, consumo_kwh, costo_paneles, superficie=10, tarifa_kwh=600):
    """Calcular generación solar y análisis financiero"""
    try:
        # Validar entradas
        if any(val <= 0 for val in [consumo_kwh, costo_paneles, superficie, tarifa_kwh]):
            raise ValueError("Todos los valores deben ser positivos")
        
        # Obtener radiación solar
        radiacion_diaria, radiacion_mensual = obtener_radiacion_solar(lat, lon)
        
        # Parámetros del sistema solar
        eficiencia_panel = 0.20  # 20% eficiencia típica de paneles comerciales
        eficiencia_inversor = 0.95  # 95% eficiencia inversor
        factor_perdidas = 0.85  # Pérdidas por cableado, suciedad, sombras, etc.
        
        eficiencia_sistema = eficiencia_panel * eficiencia_inversor * factor_perdidas
        
        # Cálculo de generación de energía
        # Potencia instalada (kW) = Superficie * 1000 W/m² * eficiencia_panel / 1000
        potencia_instalada_kw = superficie * eficiencia_panel
        
        # Generación diaria = Radiación * Potencia * Eficiencia del sistema
        generacion_diaria_kwh = radiacion_diaria * potencia_instalada_kw * (eficiencia_inversor * factor_perdidas)
        generacion_mensual_kwh = generacion_diaria_kwh * 30.44  # Promedio días por mes
        generacion_anual_kwh = generacion_diaria_kwh * 365
        
        # Análisis financiero
        energia_autoconsumida = min(generacion_mensual_kwh, consumo_kwh)
        exceso_energia = max(0, generacion_mensual_kwh - consumo_kwh)
        
        # Ahorro mensual solo por autoconsumo (sin venta de excesos por simplicidad)
        ahorro_mensual = energia_autoconsumida * tarifa_kwh
        ahorro_anual = ahorro_mensual * 12
        
        # Cálculo de ROI y payback
        if ahorro_anual > 0:
            payback_años = costo_paneles / ahorro_anual
            # ROI a 25 años (vida útil típica de paneles)
            ingreso_total_25_años = ahorro_anual * 25
            roi_porcentaje = ((ingreso_total_25_años - costo_paneles) / costo_paneles) * 100
        else:
            payback_años = float('inf')
            roi_porcentaje = 0
        
        # Impacto ambiental
        factor_emisiones = 0.5  # kg CO2 por kWh (promedio Colombia)
        co2_evitado_anual = generacion_anual_kwh * factor_emisiones
        
        # Análisis por estaciones (si tenemos datos mensuales)
        estaciones = {}
        if radiacion_mensual:
            try:
                # Agrupar por estaciones climáticas de Colombia
                # Época seca: Dic-Mar, Época lluviosa: Abr-Nov
                epoca_seca = [radiacion_mensual.get(str(m), 0) for m in [12, 1, 2, 3]]
                epoca_lluviosa = [radiacion_mensual.get(str(m), 0) for m in [4, 5, 6, 7, 8, 9, 10, 11]]
                
                estaciones = {
                    'epoca_seca': round(sum(epoca_seca) / len(epoca_seca), 2),
                    'epoca_lluviosa': round(sum(epoca_lluviosa) / len(epoca_lluviosa), 2)
                }
            except Exception as e:
                logger.error(f"Error calculando datos estacionales: {e}")
                estaciones = {}
        
        resultado = {
            'generacion_diaria_kwh': round(generacion_diaria_kwh, 2),
            'generacion_mensual_kwh': round(generacion_mensual_kwh, 2),
            'generacion_anual_kwh': round(generacion_anual_kwh, 2),
            'ahorro_mensual': round(ahorro_mensual, 0),
            'ahorro_anual': round(ahorro_anual, 0),
            'payback_años': round(payback_años, 1) if payback_años != float('inf') else 'N/A',
            'roi_porcentaje': round(roi_porcentaje, 1),
            'co2_evitado_anual': round(co2_evitado_anual, 0),
            'radiacion_diaria': round(radiacion_diaria, 2),
            'eficiencia_sistema': round(eficiencia_sistema * 100, 1),
            'potencia_instalada_kw': round(potencia_instalada_kw, 2),
            'estaciones': estaciones,
            'energia_autoconsumida': round(energia_autoconsumida, 2),
            'exceso_energia': round(exceso_energia, 2)
        }
        
        logger.info(f"Cálculo completado exitosamente: {resultado}")
        return resultado
        
    except Exception as e:
        logger.error(f"Error en cálculos solares: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise

@app.route('/')
def index():
    """Página principal"""
    return render_template('index.html')

@app.route('/api/calcular', methods=['POST'])
def api_calcular():
    """API endpoint para cálculos solares"""
    try:
        data = request.get_json()
        logger.info(f"Datos recibidos: {data}")
        
        # Validar datos requeridos
        required_fields = ['lat', 'lon', 'consumo', 'costo']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Campo requerido: {field}'}), 400
        
        # Validar coordenadas
        valido, resultado = validar_coordenadas(data['lat'], data['lon'])
        if not valido:
            return jsonify({'error': resultado}), 400
        
        lat, lon = resultado
        
        # Convertir y validar otros valores
        try:
            consumo = float(data['consumo'])
            costo = float(data['costo'])
            superficie = float(data.get('superficie', 10))
            tarifa = float(data.get('tarifa', 600))
        except (ValueError, TypeError):
            return jsonify({'error': 'Valores numéricos inválidos'}), 400
        
        # Validar valores positivos
        if any(val <= 0 for val in [consumo, costo, superficie, tarifa]):
            return jsonify({'error': 'Todos los valores deben ser positivos'}), 400
        
        # Calcular datos solares
        resultados = calcular_datos_solares(lat, lon, consumo, costo, superficie, tarifa)
        
        # Agregar metadatos
        resultados['timestamp'] = datetime.now().isoformat()
        resultados['ubicacion'] = {'lat': lat, 'lon': lon}
        
        return jsonify({
            'success': True,
            'data': resultados
        })
        
    except ValueError as e:
        logger.error(f"Error de validación: {e}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error interno: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/radiacion/<float:lat>/<float:lon>')
def api_radiacion(lat, lon):
    """API endpoint para obtener solo datos de radiación"""
    try:
        # Validar coordenadas
        valido, resultado = validar_coordenadas(lat, lon)
        if not valido:
            return jsonify({'error': resultado}), 400
        
        lat, lon = resultado
        radiacion_diaria, radiacion_mensual = obtener_radiacion_solar(lat, lon)
        
        return jsonify({
            'success': True,
            'data': {
                'radiacion_diaria': round(radiacion_diaria, 2),
                'radiacion_mensual': radiacion_mensual,
                'ubicacion': {'lat': lat, 'lon': lon}
            }
        })
        
    except Exception as e:
        logger.error(f"Error obteniendo radiación: {e}")
        return jsonify({'error': 'Error obteniendo datos de radiación'}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint no encontrado'}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Error 500: {error}")
    return jsonify({'error': 'Error interno del servidor'}), 500

if __name__ == '__main__':
    # Configuración para desarrollo
    debug_mode = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    
    logger.info(f"Iniciando servidor en {host}:{port}")
    app.run(debug=debug_mode, host=host, port=port)