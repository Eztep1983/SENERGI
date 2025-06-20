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
        url = f"https://power.larc.nasa.gov/api/temporal/climatology/point"
        params = {
            'parameters': 'ALLSKY_SFC_SW_DWN',
            'community': 'RE',
            'longitude': lon,
            'latitude': lat,
            'format': 'JSON'
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        radiacion_mensual = data['properties']['parameter']['ALLSKY_SFC_SW_DWN']
        
        # Calcular promedio anual
        radiacion_anual = sum(radiacion_mensual.values())
        radiacion_promedio_diaria = radiacion_anual / 365
        
        return radiacion_promedio_diaria, radiacion_mensual
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error al obtener datos de NASA POWER: {e}")
        # Fallback con valores estimados para Nariño
        return 4.5, None
    except Exception as e:
        logger.error(f"Error procesando datos de radiación: {e}")
        return 4.5, None

def calcular_datos_solares(lat, lon, consumo_kwh, costo_paneles, superficie=10, tarifa_kwh=700):
    """Calcular generación solar y análisis financiero"""
    try:
        # Validar entradas
        if any(val <= 0 for val in [consumo_kwh, costo_paneles, superficie, tarifa_kwh]):
            raise ValueError("Todos los valores deben ser positivos")
        
        # Obtener radiación solar
        radiacion_diaria, radiacion_mensual = obtener_radiacion_solar(lat, lon)
        
        # Parámetros del sistema
        eficiencia_panel = 0.22  # 22% eficiencia típica
        eficiencia_inversor = 0.95  # 95% eficiencia inversor
        factor_perdidas = 0.85  # Pérdidas por cableado, suciedad, etc.
        
        eficiencia_sistema = eficiencia_panel * eficiencia_inversor * factor_perdidas
        
        # Cálculo de generación
        generacion_diaria_kwh = radiacion_diaria * eficiencia_sistema * superficie
        generacion_mensual_kwh = generacion_diaria_kwh * 30.44  # Promedio días por mes
        generacion_anual_kwh = generacion_diaria_kwh * 365
        
        # Análisis financiero
        energia_autoconsumida = min(generacion_mensual_kwh, consumo_kwh)
        ahorro_mensual = energia_autoconsumida * tarifa_kwh
        ahorro_anual = ahorro_mensual * 12
        
        # ROI y payback
        if ahorro_anual > 0:
            payback_años = costo_paneles / ahorro_anual
            roi_porcentaje = (ahorro_anual / costo_paneles) * 100
        else:
            payback_años = float('inf')
            roi_porcentaje = 0
        
        # Impacto ambiental
        factor_emisiones = 0.5  # kg CO2 por kWh (promedio Colombia)
        co2_evitado_anual = generacion_anual_kwh * factor_emisiones
        
        # Análisis por estaciones (si tenemos datos mensuales)
        estaciones = {}
        if radiacion_mensual:
            # Agrupar por estaciones
            verano = [radiacion_mensual[str(m)] for m in [12, 1, 2]]  # Dic, Ene, Feb
            otoño = [radiacion_mensual[str(m)] for m in [3, 4, 5]]   # Mar, Abr, May
            invierno = [radiacion_mensual[str(m)] for m in [6, 7, 8]]  # Jun, Jul, Ago
            primavera = [radiacion_mensual[str(m)] for m in [9, 10, 11]]  # Sep, Oct, Nov
            
            estaciones = {
                'verano': sum(verano) / len(verano),
                'otoño': sum(otoño) / len(otoño),
                'invierno': sum(invierno) / len(invierno),
                'primavera': sum(primavera) / len(primavera)
            }
        
        return {
            'generacion_mensual_kwh': round(generacion_mensual_kwh, 2),
            'generacion_anual_kwh': round(generacion_anual_kwh, 2),
            'ahorro_mensual': round(ahorro_mensual, 2),
            'ahorro_anual': round(ahorro_anual, 2),
            'payback_años': round(payback_años, 1) if payback_años != float('inf') else 'N/A',
            'roi_porcentaje': round(roi_porcentaje, 1),
            'co2_evitado_anual': round(co2_evitado_anual, 2),
            'radiacion_diaria': round(radiacion_diaria, 2),
            'eficiencia_sistema': round(eficiencia_sistema * 100, 1),
            'estaciones': estaciones,
            'energia_autoconsumida': round(energia_autoconsumida, 2),
            'exceso_energia': round(max(0, generacion_mensual_kwh - consumo_kwh), 2)
        }
        
    except Exception as e:
        logger.error(f"Error en cálculos solares: {e}")
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
        consumo = float(data['consumo'])
        costo = float(data['costo'])
        superficie = float(data.get('superficie', 10))
        tarifa = float(data.get('tarifa', 600))
        
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

@app.route('/api/geocode')
def api_geocode():
    """API endpoint para geocodificación"""
    try:
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify({'error': 'Parámetro de búsqueda requerido'}), 400
        
        # Agregar Nariño, Colombia a la búsqueda para mejores resultados
        search_query = f"{query}, Nariño, Colombia"
        
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': search_query,
            'format': 'json',
            'addressdetails': 1,
            'limit': 10,
            'countrycodes': 'co'
        }
        
        headers = {
            'User-Agent': 'SENERGI/1.0',
            'Accept-Language': 'es'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Filtrar resultados para que estén en Colombia
        resultados_filtrados = []
        for item in data:
            lat, lon = float(item['lat']), float(item['lon'])
            if -4.5 <= lat <= 13.5 and -82 <= lon <= -66:
                resultados_filtrados.append({
                    'lat': lat,
                    'lon': lon,
                    'display_name': item['display_name'],
                    'address': item.get('address', {})
                })
        
        return jsonify({
            'success': True,
            'data': resultados_filtrados
        })
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error en geocodificación: {e}")
        return jsonify({'error': 'Error en servicio de geocodificación'}), 500
    except Exception as e:
        logger.error(f"Error interno en geocodificación: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/reverse-geocode/<float:lat>/<float:lon>')
def api_reverse_geocode(lat, lon):
    """API endpoint para geocodificación inversa"""
    try:
        # Validar coordenadas
        valido, resultado = validar_coordenadas(lat, lon)
        if not valido:
            return jsonify({'error': resultado}), 400
        
        lat, lon = resultado
        
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            'lat': lat,
            'lon': lon,
            'format': 'json',
            'addressdetails': 1
        }
        
        headers = {
            'User-Agent': 'SENERGI/1.0',
            'Accept-Language': 'es'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        return jsonify({
            'success': True,
            'data': {
                'display_name': data.get('display_name', 'Dirección no disponible'),
                'address': data.get('address', {}),
                'ubicacion': {'lat': lat, 'lon': lon}
            }
        })
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error en geocodificación inversa: {e}")
        return jsonify({'error': 'Error obteniendo dirección'}), 500
    except Exception as e:
        logger.error(f"Error interno: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint no encontrado'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Error interno del servidor'}), 500

# Ruta legacy para compatibilidad con el form original
@app.route('/calcular', methods=['POST'])
def calcular_legacy():
    """Endpoint legacy para formularios HTML"""
    try:
        lat = float(request.form['lat'])
        lon = float(request.form['lon'])
        consumo = float(request.form['consumo'])
        costo = float(request.form['costo'])
        superficie = float(request.form.get('superficie', 10))
        tarifa = float(request.form.get('tarifa', 600))
        
        # Validar coordenadas
        valido, resultado = validar_coordenadas(lat, lon)
        if not valido:
            return render_template('index.html', error=resultado)
        
        lat, lon = resultado
        
        # Calcular datos solares
        resultados = calcular_datos_solares(lat, lon, consumo, costo, superficie, tarifa)
        
        return render_template('index.html', 
                             generacion=resultados['generacion_mensual_kwh'],
                             ahorro=resultados['ahorro_mensual'],
                             roi=resultados['payback_años'])
        
    except (ValueError, KeyError) as e:
        logger.error(f"Error en datos del formulario: {e}")
        return render_template('index.html', error='Datos inválidos en el formulario')
    except Exception as e:
        logger.error(f"Error en cálculo legacy: {e}")
        return render_template('index.html', error='Error en el cálculo')

if __name__ == '__main__':
    # Configuración para desarrollo
    debug_mode = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    port = int(os.environ.get('PORT', 5001))
    host = os.environ.get('HOST', '127.0.0.1')
    
    app.run(debug=debug_mode, host=host, port=port)