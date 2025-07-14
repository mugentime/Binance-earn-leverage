# main.py
import os
import requests
import hmac
import hashlib
import time
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
from dataclasses import dataclass
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, request, render_template_string

@dataclass
class AssetConfig:
    symbol: str
    ltv_max: float
    yield_rate: float
    liquidity_tier: int
    loan_rate: float
    volatility_factor: float

@dataclass
class Position:
    asset: str
    collateral_amount: float
    loan_amount: float
    loan_asset: str
    current_ltv: float
    yield_earned: float
    level: int

class MultiAssetLeverageBot:
    """
    Bot de Apalancamiento Multi-Activo con Estrategia de Cascada
    
    ADVERTENCIA: Este código es para fines educativos.
    El trading automatizado conlleva riesgos significativos.
    """
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://testnet.binance.vision" if testnet else "https://api.binance.com"
        self.headers = {
            'X-MBX-APIKEY': api_key,
            'Content-Type': 'application/json'
        }
        
        # Configuración de logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Configuración de activos multi-tier
        self.asset_config = self._initialize_asset_config()
        
        # Configuración de estrategia
        self.max_cascade_levels = 5
        self.target_total_leverage = 2.4
        self.rebalance_threshold = 0.05
        self.emergency_ltv = 0.85
        
        # Estado del portfolio
        self.positions: List[Position] = []
        self.total_capital = 0
        self.leveraged_capital = 0
        self.total_yield = 0
        
        # Control de ejecución
        self.is_running = False
        self.last_rebalance = datetime.now()
        self.bot_status = "Stopped"
        
    def _initialize_asset_config(self) -> Dict[str, AssetConfig]:
        """Inicializa configuración de activos por tiers"""
        return {
            # Tier 1 - Alta Liquidez
            'BTC': AssetConfig('BTC', 0.70, 0.05, 1, 0.025, 0.3),
            'ETH': AssetConfig('ETH', 0.65, 0.06, 1, 0.028, 0.35),
            'BNB': AssetConfig('BNB', 0.60, 0.08, 1, 0.030, 0.4),
            
            # Tier 2 - Media Liquidez
            'AVAX': AssetConfig('AVAX', 0.55, 0.12, 2, 0.035, 0.5),
            'MATIC': AssetConfig('MATIC', 0.50, 0.15, 2, 0.032, 0.45),
            'SOL': AssetConfig('SOL', 0.52, 0.13, 2, 0.038, 0.55),
            'ADA': AssetConfig('ADA', 0.48, 0.16, 2, 0.033, 0.42),
            
            # Tier 3 - Oportunidades
            'DOT': AssetConfig('DOT', 0.45, 0.18, 3, 0.040, 0.6),
            'ATOM': AssetConfig('ATOM', 0.40, 0.20, 3, 0.042, 0.65),
            'NEAR': AssetConfig('NEAR', 0.42, 0.19, 3, 0.041, 0.58),
            'FTM': AssetConfig('FTM', 0.38, 0.22, 3, 0.045, 0.7),
            
            # Tier 4 - Alto Rendimiento
            'LUNA': AssetConfig('LUNA', 0.35, 0.25, 4, 0.048, 0.8),
            'OSMO': AssetConfig('OSMO', 0.30, 0.28, 4, 0.050, 0.85),
            'JUNO': AssetConfig('JUNO', 0.25, 0.30, 4, 0.052, 0.9),
        }
    
    def _generate_signature(self, query_string: str) -> str:
        """Genera firma HMAC para autenticación"""
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    async def _make_request(self, endpoint: str, params: Dict = None, method: str = 'GET') -> Dict:
        """Realiza peticiones asíncronas a la API"""
        if params is None:
            params = {}
        
        params['timestamp'] = int(time.time() * 1000)
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        params['signature'] = self._generate_signature(query_string)
        
        url = f"{self.base_url}{endpoint}"
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                if method == 'GET':
                    async with session.get(url, params=params) as response:
                        return await response.json()
                elif method == 'POST':
                    async with session.post(url, data=params) as response:
                        return await response.json()
            except Exception as e:
                self.logger.error(f"Error en petición API: {e}")
                return {}
    
    def calculate_cascade_structure(self, initial_capital: float) -> List[Dict]:
        """Calcula estructura de cascada de apalancamiento"""
        cascade_levels = []
        current_capital = initial_capital
        
        # Ordenar activos por score (yield/volatility ratio)
        sorted_assets = sorted(
            self.asset_config.items(),
            key=lambda x: x[1].yield_rate / (1 + x[1].volatility_factor),
            reverse=True
        )
        
        for level in range(self.max_cascade_levels):
            if level >= len(sorted_assets) or current_capital < 100:
                break
            
            asset_name, asset_config = sorted_assets[level]
            max_loan = current_capital * asset_config.ltv_max
            
            cascade_levels.append({
                'level': level + 1,
                'collateral_asset': asset_name,
                'collateral_amount': current_capital,
                'loan_amount': max_loan,
                'loan_asset': 'USDT',
                'next_purchase_asset': sorted_assets[(level + 1) % len(sorted_assets)][0],
                'expected_yield': asset_config.yield_rate,
                'loan_cost': asset_config.loan_rate,
                'net_yield': asset_config.yield_rate - asset_config.loan_rate
            })
            
            current_capital = max_loan * 0.95
        
        return cascade_levels
    
    async def start_simulation(self, initial_capital: float):
        """Inicia simulación del bot"""
        try:
            self.logger.info(f"Iniciando simulación con capital: ${initial_capital}")
            self.total_capital = initial_capital
            self.is_running = True
            self.bot_status = "Running"
            
            # Calcular estructura de cascada
            cascade_structure = self.calculate_cascade_structure(initial_capital)
            
            # Simular posiciones
            total_leveraged = 0
            for cascade_level in cascade_structure:
                position = Position(
                    asset=cascade_level['collateral_asset'],
                    collateral_amount=cascade_level['collateral_amount'],
                    loan_amount=cascade_level['loan_amount'],
                    loan_asset=cascade_level['loan_asset'],
                    current_ltv=cascade_level['loan_amount'] / cascade_level['collateral_amount'],
                    yield_earned=0,
                    level=cascade_level['level']
                )
                self.positions.append(position)
                total_leveraged += cascade_level['loan_amount']
            
            self.leveraged_capital = total_leveraged
            
            # Calcular rendimiento estimado
            annual_yield = sum((l['net_yield']) * l['loan_amount'] for l in cascade_structure)
            self.total_yield = (annual_yield / initial_capital) * 100
            
            self.logger.info(f"Simulación iniciada exitosamente")
            
        except Exception as e:
            self.logger.error(f"Error en simulación: {e}")
            self.bot_status = "Error"
    
    def stop_bot(self):
        """Detiene el bot"""
        self.is_running = False
        self.bot_status = "Stopped"
        self.positions.clear()
        self.logger.info("Bot detenido")
    
    def get_portfolio_status(self) -> Dict:
        """Obtiene estado actual del portfolio"""
        return {
            'bot_status': self.bot_status,
            'total_positions': len(self.positions),
            'total_capital': self.total_capital,
            'leveraged_capital': self.leveraged_capital,
            'total_yield': self.total_yield,
            'leverage_ratio': self.leveraged_capital / self.total_capital if self.total_capital > 0 else 0,
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'positions': [
                {
                    'asset': pos.asset,
                    'collateral': pos.collateral_amount,
                    'loan': pos.loan_amount,
                    'ltv': pos.current_ltv,
                    'level': pos.level
                }
                for pos in self.positions
            ]
        }

# Crear instancia global del bot
bot = None

# Flask App
app = Flask(__name__)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Multi-Asset Leverage Bot</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
        .header { text-align: center; color: #333; margin-bottom: 30px; }
        .controls { background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
        .status { display: flex; justify-content: space-between; margin-bottom: 20px; }
        .metric { background: #007bff; color: white; padding: 15px; border-radius: 8px; text-align: center; flex: 1; margin: 0 5px; }
        .metric.yield { background: #28a745; }
        .metric.leverage { background: #ffc107; color: #333; }
        .metric.positions { background: #17a2b8; }
        .positions-table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        .positions-table th, .positions-table td { border: 1px solid #ddd; padding: 12px; text-align: left; }
        .positions-table th { background: #f8f9fa; }
        .btn { padding: 10px 20px; margin: 5px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; }
        .btn-primary { background: #007bff; color: white; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-success { background: #28a745; color: white; }
        .input-group { margin: 10px 0; }
        .input-group label { display: block; margin-bottom: 5px; }
        .input-group input { width: 200px; padding: 8px; border: 1px solid #ddd; border-radius: 4px; }
        .status-indicator { padding: 5px 10px; border-radius: 20px; color: white; font-weight: bold; }
        .status-running { background: #28a745; }
        .status-stopped { background: #dc3545; }
        .status-error { background: #ffc107; color: #333; }
        .asset-config { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px; margin: 20px 0; }
        .asset-card { background: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 4px solid #007bff; }
        .tier-1 { border-left-color: #28a745; }
        .tier-2 { border-left-color: #ffc107; }
        .tier-3 { border-left-color: #fd7e14; }
        .tier-4 { border-left-color: #dc3545; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Multi-Asset Leverage Bot</h1>
            <p>Estrategia de Apalancamiento en Cascada Multi-Activo</p>
        </div>
        
        <div class="controls">
            <h3>Control del Bot</h3>
            <div class="input-group">
                <label for="capital">Capital Inicial (USD):</label>
                <input type="number" id="capital" value="10000" min="100" step="100">
            </div>
            <button class="btn btn-success" onclick="startBot()">Iniciar Bot</button>
            <button class="btn btn-danger" onclick="stopBot()">Detener Bot</button>
            <button class="btn btn-primary" onclick="updateStatus()">Actualizar Estado</button>
        </div>
        
        <div class="status" id="status">
            <div class="metric">
                <div>Estado</div>
                <div><span id="bot-status" class="status-indicator status-stopped">Detenido</span></div>
            </div>
            <div class="metric">
                <div>Capital Total</div>
                <div>$<span id="total-capital">0</span></div>
            </div>
            <div class="metric leverage">
                <div>Capital Apalancado</div>
                <div>$<span id="leveraged-capital">0</span></div>
            </div>
            <div class="metric yield">
                <div>ROI Estimado</div>
                <div><span id="total-yield">0</span>%</div>
            </div>
            <div class="metric positions">
                <div>Posiciones Activas</div>
                <div><span id="total-positions">0</span></div>
            </div>
        </div>
        
        <div>
            <h3>Configuración de Activos</h3>
            <div class="asset-config" id="asset-config"></div>
        </div>
        
        <div>
            <h3>Posiciones Activas</h3>
            <table class="positions-table" id="positions-table">
                <thead>
                    <tr>
                        <th>Nivel</th>
                        <th>Activo</th>
                        <th>Colateral</th>
                        <th>Préstamo</th>
                        <th>LTV</th>
                        <th>Estado</th>
                    </tr>
                </thead>
                <tbody id="positions-body">
                    <tr>
                        <td colspan="6" style="text-align: center; color: #666;">No hay posiciones activas</td>
                    </tr>
                </tbody>
            </table>
        </div>
        
        <div style="margin-top: 30px; padding: 20px; background: #fff3cd; border-radius: 8px; border-left: 4px solid #ffc107;">
            <h4>⚠️ Advertencia Importante</h4>
            <p>Este bot está en modo simulación para fines educativos. El trading con apalancamiento conlleva riesgos significativos. Siempre pruebe en testnet antes de usar capital real.</p>
        </div>
    </div>

    <script>
        async function startBot() {
            const capital = document.getElementById('capital').value;
            try {
                const response = await fetch('/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ capital: parseFloat(capital) })
                });
                const result = await response.json();
                if (result.success) {
                    setTimeout(updateStatus, 1000);
                }
            } catch (error) {
                console.error('Error:', error);
            }
        }
        
        async function stopBot() {
            try {
                const response = await fetch('/stop', { method: 'POST' });
                const result = await response.json();
                if (result.success) {
                    setTimeout(updateStatus, 1000);
                }
            } catch (error) {
                console.error('Error:', error);
            }
        }
        
        async function updateStatus() {
            try {
                const response = await fetch('/status');
                const data = await response.json();
                
                // Actualizar métricas
                document.getElementById('total-capital').textContent = data.total_capital.toLocaleString();
                document.getElementById('leveraged-capital').textContent = data.leveraged_capital.toLocaleString();
                document.getElementById('total-yield').textContent = data.total_yield.toFixed(2);
                document.getElementById('total-positions').textContent = data.total_positions;
                
                // Actualizar estado del bot
                const statusElement = document.getElementById('bot-status');
                statusElement.textContent = data.bot_status;
                statusElement.className = 'status-indicator status-' + data.bot_status.toLowerCase();
                
                // Actualizar tabla de posiciones
                const tbody = document.getElementById('positions-body');
                tbody.innerHTML = '';
                
                if (data.positions.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #666;">No hay posiciones activas</td></tr>';
                } else {
                    data.positions.forEach(pos => {
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>${pos.level}</td>
                            <td>${pos.asset}</td>
                            <td>$${pos.collateral.toLocaleString()}</td>
                            <td>$${pos.loan.toLocaleString()}</td>
                            <td>${(pos.ltv * 100).toFixed(1)}%</td>
                            <td><span class="status-indicator status-running">Activa</span></td>
                        `;
                        tbody.appendChild(row);
                    });
                }
            } catch (error) {
                console.error('Error:', error);
            }
        }
        
        async function loadAssetConfig() {
            try {
                const response = await fetch('/assets');
                const assets = await response.json();
                const container = document.getElementById('asset-config');
                container.innerHTML = '';
                
                Object.entries(assets).forEach(([asset, config]) => {
                    const card = document.createElement('div');
                    card.className = `asset-card tier-${config.liquidity_tier}`;
                    card.innerHTML = `
                        <h4>${asset}</h4>
                        <p><strong>LTV Máximo:</strong> ${(config.ltv_max * 100).toFixed(0)}%</p>
                        <p><strong>Yield:</strong> ${(config.yield_rate * 100).toFixed(1)}%</p>
                        <p><strong>Costo Préstamo:</strong> ${(config.loan_rate * 100).toFixed(1)}%</p>
                        <p><strong>Ganancia Neta:</strong> ${((config.yield_rate - config.loan_rate) * 100).toFixed(1)}%</p>
                        <p><strong>Tier:</strong> ${config.liquidity_tier}</p>
                    `;
                    container.appendChild(card);
                });
            } catch (error) {
                console.error('Error:', error);
            }
        }
        
        // Actualizar cada 10 segundos
        setInterval(updateStatus, 10000);
        
        // Cargar configuración inicial
        loadAssetConfig();
        updateStatus();
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/start', methods=['POST'])
def start_bot():
    global bot
    try:
        data = request.get_json()
        capital = data.get('capital', 10000)
        
        # Crear nueva instancia del bot
        api_key = os.getenv('BINANCE_API_KEY', 'demo_key')
        api_secret = os.getenv('BINANCE_API_SECRET', 'demo_secret')
        
        bot = MultiAssetLeverageBot(api_key, api_secret, testnet=True)
        
        # Iniciar simulación
        asyncio.create_task(bot.start_simulation(capital))
        
        return jsonify({'success': True, 'message': 'Bot iniciado exitosamente'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/stop', methods=['POST'])
def stop_bot():
    global bot
    try:
        if bot:
            bot.stop_bot()
        return jsonify({'success': True, 'message': 'Bot detenido exitosamente'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/status')
def get_status():
    global bot
    if bot:
        return jsonify(bot.get_portfolio_status())
    else:
        return jsonify({
            'bot_status': 'Stopped',
            'total_positions': 0,
            'total_capital': 0,
            'leveraged_capital': 0,
            'total_yield': 0,
            'leverage_ratio': 0,
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'positions': []
        })

@app.route('/assets')
def get_assets():
    global bot
    if bot:
        return jsonify(bot.asset_config)
    else:
        # Retornar configuración por defecto
        temp_bot = MultiAssetLeverageBot('demo', 'demo')
        return jsonify(temp_bot.asset_config)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)