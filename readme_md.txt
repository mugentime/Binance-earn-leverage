# Multi-Asset Leverage Bot

🚀 **Bot de Apalancamiento Multi-Activo con Estrategia de Cascada**

Aplicación web que implementa una estrategia automatizada de apalancamiento en cascada utilizando múltiples activos de Binance para maximizar el rendimiento del capital.

## 🎯 Estrategia

### Concepto Principal
- **Apalancamiento en Cascada**: Cada préstamo genera nuevo colateral para el siguiente nivel
- **Multi-Activo**: Utiliza 15+ activos organizados en 4 tiers de liquidez
- **Delta-Neutral**: Mantiene exposición mínima a movimientos de precio
- **Carry Lending**: Genera rendimientos por diferencias entre yields y costos de préstamo

### Estructura de Tiers
- **Tier 1**: BTC, ETH, BNB (Alta liquidez, LTV 60-70%)
- **Tier 2**: AVAX, MATIC, SOL, ADA (Media liquidez, LTV 48-55%)
- **Tier 3**: DOT, ATOM, NEAR, FTM (Oportunidades, LTV 38-45%)
- **Tier 4**: LUNA, OSMO, JUNO (Alto rendimiento, LTV 25-35%)

## 📊 Rendimiento Proyectado

Con **$10,000 iniciales**:
- Capital apalancado total: **~$24,000**
- Apalancamiento efectivo: **2.4x**
- ROI estimado: **13-15% anual**
- Rendimiento absoluto: **$1,300-1,500/año**

## 🛠️ Características

### ✅ Implementado
- [x] Sistema multi-activo con 15 criptomonedas
- [x] Apalancamiento en cascada de hasta 5 niveles
- [x] Dashboard web interactivo
- [x] Simulación en tiempo real
- [x] Gestión de riesgo automatizada
- [x] Configuración por tiers de liquidez

### 🔄 Modo Simulación
- Actualmente funciona en **modo simulación** para demostrar la estrategia
- No requiere API keys reales de Binance
- Calcula rendimientos basados en datos históricos

### 🔮 Próximas Características
- [ ] Integración real con Binance API
- [ ] Monitoreo en tiempo real
- [ ] Alertas automáticas
- [ ] Rebalanceo automático
- [ ] Sistema de stop-loss/take-profit

## 🚀 Deploy en Railway

### 1. Preparar Repositorio
```bash
git clone <tu-repo>
cd multi-asset-leverage-bot
```

### 2. Archivos Incluidos
```
/
├── main.py              # Aplicación principal
├── requirements.txt     # Dependencias Python
├── Procfile            # Comando de inicio
├── railway.json        # Configuración Railway
└── README.md           # Este archivo
```

### 3. Deploy
1. Conecta tu repositorio a Railway
2. Railway detectará automáticamente la aplicación Python
3. Se desplegará usando Gunicorn
4. La app estará disponible en tu dominio Railway

### 4. Variables de Entorno (Opcionales)
```
BINANCE_API_KEY=tu_api_key_aqui
BINANCE_API_SECRET=tu_api_secret_aqui
```

## 🖥️ Uso de la Aplicación

### Dashboard Principal
- **Control del Bot**: Iniciar/detener con capital personalizado
- **Métricas en Tiempo Real**: Capital, apalancamiento, ROI, posiciones
- **Configuración de Activos**: Visualización de parámetros por tier
- **Tabla de Posiciones**: Estado detallado de cada posición activa

### Controles Disponibles
1. **Iniciar Bot**: Especifica capital inicial y ejecuta estrategia
2. **Detener Bot**: Para todas las operaciones
3. **Actualizar Estado**: Refresca métricas manualmente
4. **Auto-actualización**: Cada 10 segundos automáticamente

## ⚠️ Advertencias Importantes

### Riesgos del Trading con Apalancamiento
- **Pérdidas amplificadas**: El apalancamiento puede multiplicar tanto ganancias como pérdidas
- **Liquidación forzosa**: Si el LTV supera los límites, las posiciones pueden ser liquidadas
- **Volatilidad del mercado**: Los precios de criptomonedas son altamente volátiles
- **Riesgo de contraparte**: Dependencia de la estabilidad de Binance
- **Riesgo técnico**: Fallos en APIs o conectividad pueden afectar operaciones

### Recomendaciones de Seguridad
1. **Comenzar pequeño**: Prueba con cantidades mínimas
2. **Usar testnet**: Siempre probar en entorno de pruebas primero
3. **Monitoreo constante**: Supervisar posiciones regularmente
4. **Límites de riesgo**: No invertir más de lo que puedes permitirte perder
5. **Educación continua**: Entender completamente la estrategia antes de usar

## 🔧 Desarrollo y Personalización

### Estructura del Código
```python
# Configuración de activos
asset_config = {
    'BTC': AssetConfig('BTC', ltv_max=0.70, yield_rate=0.05, ...),
    # ... más activos
}

# Parámetros de estrategia
max_cascade_levels = 5
target_total_leverage = 2.4
emergency_ltv = 0.85
```

### Personalizar Estrategia
- **Modificar tiers**: Ajustar `liquidity_tier` en configuración
- **Cambiar LTV**: Modificar `ltv_max` para controlar riesgo
- **Ajustar yields**: Actualizar `yield_rate` y `loan_rate` según mercado
- **Límites de riesgo**: Modificar `emergency_ltv` y otros parámetros

### API Endpoints
- `GET /` - Dashboard principal
- `POST /start` - Iniciar bot con capital
- `POST /stop` - Detener bot
- `GET /status` - Estado actual del portfolio
- `GET /assets` - Configuración de activos

## 📈 Métricas y Análisis

### Indicadores Clave
- **Capital Total**: Inversión inicial
- **Capital Apalancado**: Total de fondos en operación
- **Ratio de Apalancamiento**: Multiplicador efectivo
- **ROI Estimado**: Rendimiento anual proyectado
- **Posiciones Activas**: Número de operaciones abiertas

### Cálculo de Rendimiento
```python
net_yield = yield_rate - loan_rate
annual_return = sum(net_yield * loan_amount for each position)
roi_percentage = (annual_return / initial_capital) * 100
```

## 🛡️ Gestión de Riesgo

### Sistemas de Protección
- **LTV Monitoring**: Vigilancia continua de ratios de préstamo
- **Emergency Liquidation**: Cierre automático si LTV > 85%
- **Tier-based Limits**: Límites específicos por nivel de liquidez
- **Diversification**: Distribución automática entre múltiples activos

### Alertas Automáticas
- LTV > 75%: Reducción de posición
- LTV > 80%: Liquidación parcial
- LTV > 85%: Liquidación de emergencia
- Spread < 1%: Cierre de posición no rentable

## 📞 Soporte y Contacto

### Recursos Adicionales
- [Documentación Binance API](https://binance-docs.github.io/apidocs/)
- [Railway Documentation](https://docs.railway.app/)
- [Gestión de Riesgo en Trading](https://www.investopedia.com/articles/trading/09/risk-management.asp)

### Contribuciones
Las contribuciones son bienvenidas! Por favor:
1. Fork el repositorio
2. Crea una rama para tu feature
3. Commit tus cambios
4. Push a la rama
5. Abre un Pull Request

## 📄 Licencia

Este proyecto es para fines educativos. Úsalo bajo tu propia responsabilidad.

---

**⚡ Desarrollado con Railway | 🚀 Optimizado para rendimiento máximo**