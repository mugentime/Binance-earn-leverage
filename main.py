# main.py - Complete Multi-Asset Leverage Bot with Real Binance Data
import os
import requests
import hmac
import hashlib
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
from dataclasses import dataclass
import asyncio
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, request, render_template_string
import threading

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

@dataclass
class EarnPair:
    collateral_asset: str
    borrow_asset: str
    collateral_rate: float
    borrow_rate: float
    net_rate: float
    ltv_ratio: float
    profit_potential: float
    risk_score: float

class BinanceEarnAPI:
    """Real Binance API integration for earn data"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.binance.com" if not testnet else "https://testnet.binance.vision"
        self.headers = {'X-MBX-APIKEY': api_key}
        
    def _generate_signature(self, query_string: str) -> str:
        """Generate signature for Binance API"""
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _make_request(self, endpoint: str, params: Dict = None) -> Dict:
        """Make authenticated request to Binance API"""
        if params is None:
            params = {}
        
        params['timestamp'] = int(time.time() * 1000)
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        params['signature'] = self._generate_signature(query_string)
        
        try:
            response = requests.get(f"{self.base_url}{endpoint}", params=params, headers=self.headers)
            return response.json()
        except Exception as e:
            logging.error(f"API request failed: {e}")
            return {}
    
    def get_lending_products(self) -> List[Dict]:
        """Get available lending products"""
        endpoint = "/sapi/v1/lending/daily/product/list"
        params = {"status": "ALL"}
        return self.._make_request(endpoint, params).get('data', [])
    
    def get_collateral_assets(self) -> List[Dict]:
        """Get assets available as collateral"""
        endpoint = "/sapi/v1/margin/isolated/allPairs"
        return self._make_request(endpoint).get('data', [])
    
    def get_margin_interest_rates(self) -> List[Dict]:
        """Get current margin interest rates"""
        endpoint = "/sapi/v1/margin/interestRateHistory"
        params = {"limit": 100}
        return self._make_request(endpoint).get('data', [])
    
    def get_flexible_products(self) -> List[Dict]:
        """Get flexible savings products"""
        endpoint = "/sapi/v1/lending/daily/product/list"
        params = {"status": "PURCHASING", "featured": "ALL"}
        return self._make_request(endpoint).get('data', [])

class MultiAssetLeverageBot:
    """Multi-Asset Leverage Bot with Real Binance Integration"""
    
    def __init__(self, api_key: str = "demo", api_secret: str = "demo", testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        
        # Initialize Binance API
        if api_key != "demo" and api_secret != "demo":
            self.binance_api = BinanceEarnAPI(api_key, api_secret, testnet)
        else:
            self.binance_api = None
        
        # Logging setup
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
        
        # Asset configuration
        self.asset_config = self._initialize_asset_config()
        
        # Strategy configuration
        self.max_cascade_levels = 5
        self.target_total_leverage = 2.4
        self.rebalance_threshold = 0.05
        self.emergency_ltv = 0.85
        
        # Portfolio state
        self.positions: List[Position] = []
        self.total_capital = 0
        self.leveraged_capital = 0
        self.total_yield = 0
        
        # Control state
        self.is_running = False
        self.last_rebalance = datetime.now()
        self.bot_status = "Stopped"
        
        # Best pair tracking
        self.best_earn_pair = None
        self.last_pair_update = datetime.now() - timedelta(hours=1)
        
        # Start background pair analysis
        self._start_pair_analysis_thread()
    
    def _initialize_asset_config(self) -> Dict[str, AssetConfig]:
        """Initialize asset configuration with real data when possible"""
        # Complete configuration based on uploaded token list
        base_config = {
            # Tier 1 - Blue Chip Assets (Highest Liquidity, Lowest Risk)
            'BTC': AssetConfig('BTC', 0.75, 0.04, 1, 0.022, 0.25),
            'ETH': AssetConfig('ETH', 0.70, 0.05, 1, 0.025, 0.30),
            'BNB': AssetConfig('BNB', 0.65, 0.07, 1, 0.028, 0.35),
            'USDT': AssetConfig('USDT', 0.85, 0.08, 1, 0.020, 0.10),
            'USDC': AssetConfig('USDC', 0.85, 0.075, 1, 0.021, 0.10),
            
            # Tier 2 - Established DeFi (High Liquidity, Medium Risk)
            'CVX': AssetConfig('CVX', 0.55, 0.12, 2, 0.035, 0.50),
            'ZRX': AssetConfig('ZRX', 0.50, 0.14, 2, 0.038, 0.55),
            'ETHFI': AssetConfig('ETHFI', 0.45, 0.16, 2, 0.040, 0.60),
            'HIFI': AssetConfig('HIFI', 0.40, 0.18, 2, 0.042, 0.65),
            
            # Tier 3 - Mid-Cap Established (Medium Liquidity, Medium-High Risk)
            'ONT': AssetConfig('ONT', 0.45, 0.15, 3, 0.039, 0.58),
            'LIT': AssetConfig('LIT', 0.42, 0.17, 3, 0.041, 0.62),
            'LSK': AssetConfig('LSK', 0.40, 0.19, 3, 0.043, 0.65),
            'SKL': AssetConfig('SKL', 0.38, 0.21, 3, 0.045, 0.68),
            'GLMR': AssetConfig('GLMR', 0.35, 0.22, 3, 0.046, 0.70),
            'RIF': AssetConfig('RIF', 0.33, 0.24, 3, 0.048, 0.72),
            'FLM': AssetConfig('FLM', 0.30, 0.26, 3, 0.050, 0.75),
            'STPT': AssetConfig('STPT', 0.32, 0.25, 3, 0.049, 0.73),
            'DUSK': AssetConfig('DUSK', 0.35, 0.23, 3, 0.047, 0.69),
            
            # Tier 4 - Higher Risk/Reward (Lower Liquidity, High Risk/Reward)
            'BNX': AssetConfig('BNX', 0.30, 0.28, 4, 0.052, 0.80),
            'BOME': AssetConfig('BOME', 0.25, 0.32, 4, 0.058, 0.90),
            'OXT': AssetConfig('OXT', 0.28, 0.30, 4, 0.055, 0.85),
            'RONIN': AssetConfig('RONIN', 0.35, 0.27, 4, 0.051, 0.78),
            'WIF': AssetConfig('WIF', 0.22, 0.35, 4, 0.062, 0.95),
            'XVG': AssetConfig('XVG', 0.25, 0.33, 4, 0.060, 0.88),
        }
        
        # Update with real rates if API available
        if self.binance_api:
            try:
                self._update_rates_from_binance(base_config)
            except Exception as e:
                self.logger.warning(f"Could not update rates from Binance: {e}")
        
        return base_config
    
    def _update_rates_from_binance(self, config: Dict[str, AssetConfig]):
        """Update asset configuration with real Binance rates"""
        try:
            # Get flexible products for earn rates
            flexible_products = self.binance_api.get_flexible_products()
            
            for product in flexible_products:
                asset = product.get('asset', '')
                if asset in config:
                    # Update yield rate from flexible savings
                    yield_rate = float(product.get('avgAnnualInterestRate', 0)) / 100
                    config[asset].yield_rate = max(yield_rate, config[asset].yield_rate * 0.5)
            
            # Get margin rates for borrowing costs
            margin_rates = self.binance_api.get_margin_interest_rates()
            
            for rate_data in margin_rates[-50:]:  # Last 50 entries
                asset = rate_data.get('asset', '')
                if asset in config:
                    # Update loan rate from margin data
                    daily_rate = float(rate_data.get('dailyInterestRate', 0))
                    annual_rate = daily_rate * 365
                    config[asset].loan_rate = annual_rate
                    
        except Exception as e:
            self.logger.error(f"Error updating rates from Binance: {e}")
    
    def _start_pair_analysis_thread(self):
        """Start background thread for pair analysis"""
        def analyze_pairs():
            while True:
                try:
                    if datetime.now() - self.last_pair_update > timedelta(minutes=5):
                        self._analyze_best_earn_pair()
                        self.last_pair_update = datetime.now()
                    time.sleep(60)  # Check every minute
                except Exception as e:
                    self.logger.error(f"Error in pair analysis thread: {e}")
                    time.sleep(300)  # Wait 5 minutes on error
        
        thread = threading.Thread(target=analyze_pairs, daemon=True)
        thread.start()
    
    def _analyze_best_earn_pair(self):
        """Analyze and find the best collateral/borrow pair from all available assets"""
        try:
            best_pairs = []
            
            # Get current market data and trends
            market_trends = self._get_market_trends()
            
            # Define optimal borrow assets (prefer stablecoins and low-volatility assets)
            preferred_borrow_assets = ['USDT', 'USDC', 'BTC', 'ETH']
            
            for collateral_asset, collateral_config in self.asset_config.items():
                # Skip stablecoins as collateral in most cases (lower yield potential)
                if collateral_asset in ['USDT', 'USDC']:
                    continue
                    
                for borrow_asset in preferred_borrow_assets:
                    if collateral_asset == borrow_asset or borrow_asset not in self.asset_config:
                        continue
                    
                    borrow_config = self.asset_config[borrow_asset]
                    
                    # Calculate net interest rate
                    net_rate = collateral_config.yield_rate - borrow_config.loan_rate
                    
                    # Skip if not profitable
                    if net_rate <= 0.005:  # Minimum 0.5% spread required
                        continue
                    
                    # Calculate profit potential based on price trends
                    collateral_trend = market_trends.get(collateral_asset, 0)
                    borrow_trend = market_trends.get(borrow_asset, 0)
                    
                    # Higher score if collateral is expected to outperform borrow asset
                    price_advantage = collateral_trend - borrow_trend
                    
                    # Calculate risk score (lower is better)
                    risk_score = (
                        collateral_config.volatility_factor * 0.4 +
                        borrow_config.volatility_factor * 0.2 +
                        (1 - collateral_config.ltv_max) * 0.3 +
                        (1 / collateral_config.liquidity_tier) * 0.1  # Lower tier = higher risk
                    )
                    
                    # Bonus for stablecoin borrowing (reduced volatility risk)
                    stability_bonus = 2.0 if borrow_asset in ['USDT', 'USDC'] else 1.0
                    
                    # Calculate overall profit potential
                    profit_potential = (
                        net_rate * 100 * 0.5 +      # Interest rate differential (50% weight)
                        price_advantage * 0.25 +     # Price trend advantage (25% weight)
                        (1 / risk_score) * 0.15 +    # Risk adjustment (15% weight)
                        collateral_config.ltv_max * 10 * 0.1  # LTV flexibility (10% weight)
                    ) * stability_bonus
                    
                    pair = EarnPair(
                        collateral_asset=collateral_asset,
                        borrow_asset=borrow_asset,
                        collateral_rate=collateral_config.yield_rate,
                        borrow_rate=borrow_config.loan_rate,
                        net_rate=net_rate,
                        ltv_ratio=collateral_config.ltv_max,
                        profit_potential=profit_potential,
                        risk_score=risk_score
                    )
                    
                    best_pairs.append(pair)
            
            # Sort by profit potential
            best_pairs.sort(key=lambda x: x.profit_potential, reverse=True)
            
            if best_pairs:
                self.best_earn_pair = best_pairs[0]
                self.logger.info(f"Best pair updated: {self.best_earn_pair.collateral_asset}/{self.best_earn_pair.borrow_asset} - Net: {self.best_earn_pair.net_rate*100:.2f}%")
        
        except Exception as e:
            self.logger.error(f"Error analyzing best pair: {e}")
    
    def _get_market_trends(self) -> Dict[str, float]:
        """Get market trend indicators for all assets"""
        trends = {}
        
        # Asset categories for trend bias
        blue_chip_assets = ['BTC', 'ETH', 'BNB']
        stablecoins = ['USDT', 'USDC']
        defi_assets = ['CVX', 'ZRX', 'ETHFI', 'HIFI']
        gaming_metaverse = ['BNX', 'RONIN']
        meme_assets = ['BOME', 'WIF']
        
        for asset in self.asset_config.keys():
            # Base trend calculation with some randomness for simulation
            base_trend = (hash(asset + str(datetime.now().date())) % 200 - 100) / 2000
            
            # Apply category-specific adjustments
            if asset in blue_chip_assets:
                base_trend += 0.01  # Slight positive bias for blue chips
            elif asset in stablecoins:
                base_trend = base_trend * 0.1  # Very low volatility
            elif asset in defi_assets:
                base_trend += 0.005  # Slight DeFi sector bias
            elif asset in gaming_metaverse:
                base_trend += 0.008  # Gaming sector potential
            elif asset in meme_assets:
                base_trend = base_trend * 1.5  # Higher volatility
            
            # Apply tier-based adjustment
            tier = self.asset_config[asset].liquidity_tier
            tier_adjustment = (5 - tier) * 0.002  # Higher tier = slight positive bias
            
            trends[asset] = base_trend + tier_adjustment
        
        return trends
    
    def calculate_cascade_structure(self, initial_capital: float) -> List[Dict]:
        """Calculate cascade leverage structure with all available assets"""
        cascade_levels = []
        current_capital = initial_capital
        
        # Sort assets by efficiency score (risk-adjusted yield)
        sorted_assets = sorted(
            self.asset_config.items(),
            key=lambda x: (x[1].yield_rate - x[1].loan_rate) / (1 + x[1].volatility_factor),
            reverse=True
        )
        
        # Filter out stablecoins for collateral (but keep them for borrowing)
        collateral_assets = [asset for asset in sorted_assets if asset[0] not in ['USDT', 'USDC']]
        
        for level in range(min(self.max_cascade_levels, len(collateral_assets))):
            if current_capital < 100:
                break
            
            asset_name, asset_config = collateral_assets[level]
            max_loan = current_capital * asset_config.ltv_max
            
            # Choose optimal borrow asset (preferably stablecoins for lower volatility)
            borrow_asset = 'USDT'  # Default to USDT for stability
            borrow_rate = self.asset_config['USDT'].loan_rate
            
            cascade_levels.append({
                'level': level + 1,
                'collateral_asset': asset_name,
                'collateral_amount': current_capital,
                'loan_amount': max_loan,
                'loan_asset': borrow_asset,
                'next_purchase_asset': collateral_assets[(level + 1) % len(collateral_assets)][0],
                'expected_yield': asset_config.yield_rate,
                'loan_cost': borrow_rate,
                'net_yield': asset_config.yield_rate - borrow_rate
            })
            
            current_capital = max_loan * 0.95  # 5% buffer for fees and slippage
        
        return cascade_levels
    
    async def start_simulation(self, initial_capital: float):
        """Start bot simulation"""
        try:
            self.logger.info(f"Starting simulation with capital: ${initial_capital}")
            self.total_capital = initial_capital
            self.is_running = True
            self.bot_status = "Running"
            
            # Calculate cascade structure
            cascade_structure = self.calculate_cascade_structure(initial_capital)
            
            # Create positions
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
            
            # Calculate estimated yield
            annual_yield = sum((l['net_yield']) * l['loan_amount'] for l in cascade_structure)
            self.total_yield = (annual_yield / initial_capital) * 100
            
            self.logger.info(f"Simulation started successfully")
            
        except Exception as e:
            self.logger.error(f"Simulation error: {e}")
            self.bot_status = "Error"
    
    def stop_bot(self):
        """Stop the bot"""
        self.is_running = False
        self.bot_status = "Stopped"
        self.positions.clear()
        self.logger.info("Bot stopped")
    
    def get_portfolio_status(self) -> Dict:
        """Get current portfolio status"""
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
    
    def get_best_earn_pair(self) -> Dict:
        """Get the best earn pair information"""
        if not self.best_earn_pair:
            self._analyze_best_earn_pair()
        
        if self.best_earn_pair:
            return {
                'collateral_asset': self.best_earn_pair.collateral_asset,
                'borrow_asset': self.best_earn_pair.borrow_asset,
                'collateral_rate': round(self.best_earn_pair.collateral_rate * 100, 2),
                'borrow_rate': round(self.best_earn_pair.borrow_rate * 100, 2),
                'net_rate': round(self.best_earn_pair.net_rate * 100, 2),
                'ltv_ratio': round(self.best_earn_pair.ltv_ratio * 100, 1),
                'profit_potential': round(self.best_earn_pair.profit_potential, 2),
                'last_update': self.last_pair_update.strftime('%H:%M:%S')
            }
        
        return {
            'collateral_asset': 'BTC',
            'borrow_asset': 'USDT',
            'collateral_rate': 5.0,
            'borrow_rate': 2.5,
            'net_rate': 2.5,
            'ltv_ratio': 70.0,
            'profit_potential': 8.5,
            'last_update': 'Calculating...'
        }

# Global bot instance
bot = None

# Flask Application
app = Flask(__name__)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Multi-Asset Leverage Bot</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 0; background: #f5f5f5; }
        
        /* Best Pair Banner */
        .best-pair-banner {
            background: linear-gradient(135deg, #28a745, #20c997);
            color: white;
            padding: 15px 20px;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            position: sticky;
            top: 0;
            z-index: 1000;
            animation: pulse-glow 3s infinite;
        }
        
        @keyframes pulse-glow {
            0%, 100% { box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            50% { box-shadow: 0 2px 20px rgba(40,167,69,0.3); }
        }
        
        .banner-content {
            display: flex;
            justify-content: center;
            align-items: center;
            flex-wrap: wrap;
            gap: 30px;
            max-width: 1200px;
            margin: 0 auto;
        }
        
        .banner-item {
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        
        .banner-label {
            font-size: 12px;
            opacity: 0.9;
            margin-bottom: 5px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .banner-value {
            font-size: 18px;
            font-weight: bold;
            text-shadow: 0 1px 2px rgba(0,0,0,0.2);
        }
        
        .banner-pair {
            font-size: 24px;
            font-weight: bold;
            text-shadow: 0 1px 2px rgba(0,0,0,0.2);
            letter-spacing: 2px;
        }
        
        .banner-profit {
            background: rgba(255,255,255,0.2);
            padding: 8px 15px;
            border-radius: 20px;
            font-size: 16px;
            font-weight: bold;
        }
        
        /* Main container */
        .container { 
            max-width: 1200px; 
            margin: 20px auto; 
            background: white; 
            padding: 20px; 
            border-radius: 10px; 
            box-shadow: 0 0 10px rgba(0,0,0,0.1); 
        }
        
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
        .asset-config { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 15px; margin: 20px 0; }
        .asset-card { background: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 4px solid #007bff; }
        .tier-1 { border-left-color: #28a745; }
        .tier-2 { border-left-color: #ffc107; }
        .tier-3 { border-left-color: #fd7e14; }
        .tier-4 { border-left-color: #dc3545; }
        
        @media (max-width: 768px) {
            .banner-content { flex-direction: column; gap: 15px; }
            .status { flex-direction: column; }
            .metric { margin: 5px 0; }
        }
    </style>
</head>
<body>
    <!-- Best Pair Banner -->
    <div class="best-pair-banner">
        <div class="banner-content">
            <div class="banner-item">
                <div class="banner-label">🏆 Best Earn Pair</div>
                <div class="banner-pair" id="best-pair">Loading...</div>
            </div>
            <div class="banner-item">
                <div class="banner-label">💰 Net Rate</div>
                <div class="banner-value" id="net-rate">--%</div>
            </div>
            <div class="banner-item">
                <div class="banner-label">📊 LTV Ratio</div>
                <div class="banner-value" id="ltv-ratio">--%</div>
            </div>
            <div class="banner-item">
                <div class="banner-profit" id="profit-potential">Profit Score: --</div>
            </div>
            <div class="banner-item">
                <div class="banner-label">🕒 Updated</div>
                <div class="banner-value" id="last-update">--:--</div>
            </div>
        </div>
    </div>

    <div class="container">
        <div class="header">
            <h1>🚀 Multi-Asset Leverage Bot</h1>
            <p>Advanced Cascade Leverage Strategy with 24 Premium Assets & Real-Time Market Analysis</p>
        </div>
        
        <div class="controls">
            <h3>Bot Control Panel</h3>
            <div class="input-group">
                <label for="capital">Initial Capital (USD):</label>
                <input type="number" id="capital" value="10000" min="100" step="100">
            </div>
            <button class="btn btn-success" onclick="startBot()">🚀 Start Bot</button>
            <button class="btn btn-danger" onclick="stopBot()">⛔ Stop Bot</button>
            <button class="btn btn-primary" onclick="updateStatus()">🔄 Refresh Status</button>
        </div>
        
        <div class="status" id="status">
            <div class="metric">
                <div>Bot Status</div>
                <div><span id="bot-status" class="status-indicator status-stopped">Stopped</span></div>
            </div>
            <div class="metric">
                <div>Total Capital</div>
                <div>$<span id="total-capital">0</span></div>
            </div>
            <div class="metric leverage">
                <div>Leveraged Capital</div>
                <div>$<span id="leveraged-capital">0</span></div>
            </div>
            <div class="metric yield">
                <div>Annual ROI</div>
                <div><span id="total-yield">0</span>%</div>
            </div>
            <div class="metric positions">
                <div>Active Positions</div>
                <div><span id="total-positions">0</span></div>
            </div>
        </div>
        
        <div>
            <h3>Asset Configuration & Market Data</h3>
            <div style="background: #e9ecef; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                <p><strong>Portfolio Composition:</strong> 
                   Tier 1 (Blue Chip): 5 assets | 
                   Tier 2 (Established DeFi): 4 assets | 
                   Tier 3 (Mid-Cap): 9 assets | 
                   Tier 4 (High Reward): 6 assets
                </p>
            </div>
            <div class="asset-config" id="asset-config"></div>
        </div>
        
        <div>
            <h3>Active Positions</h3>
            <table class="positions-table" id="positions-table">
                <thead>
                    <tr>
                        <th>Level</th>
                        <th>Collateral Asset</th>
                        <th>Collateral Amount</th>
                        <th>Loan Amount</th>
                        <th>LTV Ratio</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody id="positions-body">
                    <tr>
                        <td colspan="6" style="text-align: center; color: #666;">No active positions</td>
                    </tr>
                </tbody>
            </table>
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
                
                // Update metrics
                document.getElementById('total-capital').textContent = data.total_capital.toLocaleString();
                document.getElementById('leveraged-capital').textContent = data.leveraged_capital.toLocaleString();
                document.getElementById('total-yield').textContent = data.total_yield.toFixed(2);
                document.getElementById('total-positions').textContent = data.total_positions;
                
                // Update bot status
                const statusElement = document.getElementById('bot-status');
                statusElement.textContent = data.bot_status;
                statusElement.className = 'status-indicator status-' + data.bot_status.toLowerCase();
                
                // Update positions table
                const tbody = document.getElementById('positions-body');
                tbody.innerHTML = '';
                
                if (data.positions.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #666;">No active positions</td></tr>';
                } else {
                    data.positions.forEach(pos => {
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>${pos.level}</td>
                            <td>${pos.asset}</td>
                            <td>$${pos.collateral.toLocaleString()}</td>
                            <td>$${pos.loan.toLocaleString()}</td>
                            <td>${(pos.ltv * 100).toFixed(1)}%</td>
                            <td><span class="status-indicator status-running">Active</span></td>
                        `;
                        tbody.appendChild(row);
                    });
                }
            } catch (error) {
                console.error('Error:', error);
            }
        }
        
        async function updateBestPair() {
            try {
                const response = await fetch('/best-pair');
                const data = await response.json();
                
                document.getElementById('best-pair').textContent = 
                    `${data.collateral_asset}/${data.borrow_asset}`;
                document.getElementById('net-rate').textContent = 
                    `${data.net_rate}%`;
                document.getElementById('ltv-ratio').textContent = 
                    `${data.ltv_ratio}%`;
                document.getElementById('profit-potential').textContent = 
                    `Profit Score: ${data.profit_potential}`;
                document.getElementById('last-update').textContent = 
                    data.last_update;
                    
            } catch (error) {
                console.error('Error updating best pair:', error);
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
                        <p><strong>Max LTV:</strong> ${(config.ltv_max * 100).toFixed(0)}%</p>
                        <p><strong>Earn Rate:</strong> ${(config.yield_rate * 100).toFixed(2)}%</p>
                        <p><strong>Borrow Cost:</strong> ${(config.loan_rate * 100).toFixed(2)}%</p>
                        <p><strong>Net Profit:</strong> ${((config.yield_rate - config.loan_rate) * 100).toFixed(2)}%</p>
                        <p><strong>Liquidity Tier:</strong> ${config.liquidity_tier}</p>
                    `;
                    container.appendChild(card);
                });
            } catch (error) {
                console.error('Error:', error);
            }
        }
        
        // Auto-update intervals
        setInterval(updateStatus, 10000);      // Every 10 seconds
        setInterval(updateBestPair, 30000);    // Every 30 seconds
        
        // Initial load
        loadAssetConfig();
        updateStatus();
        updateBestPair();
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
        
        # Create new bot instance
        api_key = os.getenv('BINANCE_API_KEY', 'demo_key')
        api_secret = os.getenv('BINANCE_API_SECRET', 'demo_secret')
        
        bot = MultiAssetLeverageBot(api_key, api_secret, testnet=True)
        
        # Start simulation
        thread = threading.Thread(target=lambda: asyncio.run(bot.start_simulation(capital)))
        thread.start()
        
        return jsonify({'success': True, 'message': 'Bot started successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/stop', methods=['POST'])
def stop_bot():
    global bot
    try:
        if bot:
            bot.stop_bot()
        return jsonify({'success': True, 'message': 'Bot stopped successfully'})
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
        return jsonify({k: v.__dict__ for k, v in bot.asset_config.items()})
    else:
        # Return default configuration
        temp_bot = MultiAssetLeverageBot('demo', 'demo')
        return jsonify({k: v.__dict__ for k, v in temp_bot.asset_config.items()})

@app.route('/best-pair')
def get_best_pair():
    global bot
    if bot:
        return jsonify(bot.get_best_earn_pair())
    else:
        # Return default best pair
        temp_bot = MultiAssetLeverageBot('demo', 'demo')
        return jsonify(temp_bot.get_best_earn_pair())

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)