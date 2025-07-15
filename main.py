# main.py - Complete Live Trading Bot
import os
import requests
import hmac
import hashlib
import time
import json
import signal
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
from dataclasses import dataclass
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, request, render_template_string
import urllib.parse

# Global shutdown flag
shutdown_flag = threading.Event()

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logging.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_flag.set()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

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
    order_id: Optional[str] = None

class BinanceClient:
    """Binance API client with timeout and error handling"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://testnet.binance.vision" if testnet else "https://api.binance.com"
        self.headers = {
            'X-MBX-APIKEY': api_key,
            'Content-Type': 'application/json'
        }
        
    def _generate_signature(self, query_string: str) -> str:
        """Generate signature for authenticated requests"""
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _make_request(self, method: str, endpoint: str, params: dict = None, signed: bool = False) -> dict:
        """Make request with proper timeout and error handling"""
        url = f"{self.base_url}{endpoint}"
        
        if params is None:
            params = {}
        
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            query_string = urllib.parse.urlencode(params)
            params['signature'] = self._generate_signature(query_string)
        
        try:
            # Use shorter timeout for Railway deployment
            if method == 'GET':
                response = requests.get(url, headers=self.headers, params=params, timeout=5)
            elif method == 'POST':
                response = requests.post(url, headers=self.headers, params=params, timeout=5)
            elif method == 'DELETE':
                response = requests.delete(url, headers=self.headers, params=params, timeout=5)
            
            if response.status_code == 200:
                return response.json()
            else:
                # Return error info instead of raising exception
                return {'error': f"HTTP {response.status_code}: {response.text}"}
        
        except requests.exceptions.Timeout:
            return {'error': 'Request timeout'}
        except requests.exceptions.RequestException as e:
            return {'error': f"Request failed: {str(e)}"}
        except Exception as e:
            return {'error': f"Unexpected error: {str(e)}"}
    
    def test_connection(self) -> dict:
        """Test API connection - quick health check"""
        try:
            result = self._make_request('GET', '/api/v3/ping')
            if 'error' not in result:
                return {'status': 'connected', 'timestamp': datetime.now().isoformat()}
            return {'status': 'error', 'error': result['error']}
        except:
            return {'status': 'error', 'error': 'Connection failed'}
    
    def get_account_info(self) -> dict:
        """Get account information with error handling"""
        endpoint = '/sapi/v1/margin/account' if 'testnet' not in self.base_url else '/api/v3/account'
        return self._make_request('GET', endpoint, signed=True)
    
    def get_symbol_price(self, symbol: str) -> dict:
        """Get symbol price with error handling"""
        return self._make_request('GET', '/api/v3/ticker/price', {'symbol': symbol})
    
    def create_margin_order(self, symbol: str, side: str, type_: str, quantity: float, 
                          price: float = None, sideEffectType: str = "MARGIN_BUY") -> dict:
        """Create margin order"""
        params = {
            'symbol': symbol,
            'side': side,
            'type': type_,
            'quantity': quantity,
            'sideEffectType': sideEffectType
        }
        
        if price:
            params['price'] = price
            params['timeInForce'] = 'GTC'
        
        return self._make_request('POST', '/sapi/v1/margin/order', params, signed=True)
    
    def borrow_margin(self, asset: str, amount: float) -> dict:
        """Borrow asset on margin"""
        params = {
            'asset': asset,
            'amount': amount
        }
        return self._make_request('POST', '/sapi/v1/margin/loan', params, signed=True)
    
    def repay_margin(self, asset: str, amount: float) -> dict:
        """Repay margin loan"""
        params = {
            'asset': asset,
            'amount': amount
        }
        return self._make_request('POST', '/sapi/v1/margin/repay', params, signed=True)
    
    def get_margin_positions(self) -> List[dict]:
        """Get all margin positions"""
        account_info = self.get_account_info()
        if 'error' in account_info:
            return []
        return [asset for asset in account_info.get('userAssets', []) 
                if float(asset.get('free', 0)) > 0 or float(asset.get('locked', 0)) > 0]

class LiveTradingBot:
    """
    Live Trading Bot with proper deployment handling
    """
    
    def __init__(self, api_key: str = None, api_secret: str = None):
        # Setup logging for Railway
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler()]  # Only console output for Railway
        )
        self.logger = logging.getLogger(__name__)
        
        # Initialize client with provided credentials or demo mode
        self.is_live_mode = bool(api_key and api_secret and api_key != "demo" and api_key.strip())
        
        if self.is_live_mode:
            self.client = BinanceClient(api_key, api_secret, testnet=False)
            self.logger.info("🔴 LIVE MODE INITIALIZED - REAL MONEY AT RISK")
        else:
            # Demo mode for development
            self.client = None
            self.logger.info("📊 DEMO MODE - Safe for testing")
        
        # Asset configuration
        self.asset_config = self._initialize_asset_config()
        
        # Bot state
        self.positions: List[Position] = []
        self.total_capital = 0
        self.leveraged_capital = 0
        self.total_yield = 0
        self.is_running = False
        self.bot_status = "Stopped"
        self.last_update = datetime.now()
        
        # Background task
        self.monitor_task = None
        self.monitor_lock = threading.Lock()
        
    def _initialize_asset_config(self) -> Dict[str, AssetConfig]:
        """Initialize asset configuration"""
        if self.is_live_mode:
            # Conservative config for live trading
            return {
                'BTC': AssetConfig('BTC', 0.50, 0.03, 1, 0.02, 0.25),
                'ETH': AssetConfig('ETH', 0.45, 0.035, 1, 0.022, 0.28),
                'BNB': AssetConfig('BNB', 0.40, 0.04, 1, 0.025, 0.30),
                'USDC': AssetConfig('USDC', 0.85, 0.02, 1, 0.015, 0.02),
            }
        else:
            # Full config for demo mode
            return {
                'BTC': AssetConfig('BTC', 0.70, 0.05, 1, 0.025, 0.3),
                'ETH': AssetConfig('ETH', 0.65, 0.06, 1, 0.028, 0.35),
                'BNB': AssetConfig('BNB', 0.60, 0.08, 1, 0.030, 0.4),
                'AVAX': AssetConfig('AVAX', 0.55, 0.12, 2, 0.035, 0.5),
                'MATIC': AssetConfig('MATIC', 0.50, 0.15, 2, 0.032, 0.45),
                'SOL': AssetConfig('SOL', 0.52, 0.13, 2, 0.038, 0.55),
                'ADA': AssetConfig('ADA', 0.48, 0.16, 2, 0.033, 0.42),
                'DOT': AssetConfig('DOT', 0.45, 0.18, 3, 0.040, 0.6),
                'ATOM': AssetConfig('ATOM', 0.40, 0.20, 3, 0.042, 0.65),
                'NEAR': AssetConfig('NEAR', 0.42, 0.19, 3, 0.041, 0.58),
            }
    
    def start_bot(self, initial_capital: float):
        """Start bot in appropriate mode"""
        try:
            self.logger.info(f"Starting bot with ${initial_capital}")
            
            if initial_capital < 100:
                return {'success': False, 'error': 'Minimum capital is $100'}
            
            if self.is_live_mode and initial_capital > 50000:
                return {'success': False, 'error': 'Maximum capital is $50,000 for safety'}
            
            self.total_capital = initial_capital
            self.is_running = True
            
            if self.is_live_mode:
                self.bot_status = "Running (LIVE)"
                return self._start_live_trading(initial_capital)
            else:
                self.bot_status = "Running (DEMO)"
                return self._start_demo_trading(initial_capital)
                
        except Exception as e:
            self.logger.error(f"Failed to start bot: {e}")
            self.bot_status = "Error"
            return {'success': False, 'error': str(e)}
    
    def _start_live_trading(self, capital: float) -> dict:
        """Start live trading with real API"""
        try:
            # Test connection first
            connection_test = self.client.test_connection()
            if connection_test['status'] != 'connected':
                return {'success': False, 'error': f"API connection failed: {connection_test.get('error')}"}
            
            # Get account info
            account_info = self.client.get_account_info()
            if 'error' in account_info:
                return {'success': False, 'error': f"Account access failed: {account_info['error']}"}
            
            # Check USDT balance
            user_assets = account_info.get('userAssets', [])
            usdt_balance = 0
            for asset in user_assets:
                if asset.get('asset') == 'USDT':
                    usdt_balance = float(asset.get('free', 0))
                    break
            
            if usdt_balance < capital:
                return {'success': False, 'error': f"Insufficient USDT balance. Have: ${usdt_balance:.2f}, Need: ${capital}"}
            
            self.logger.info("✅ Live trading connection verified")
            
            # Execute live trading strategy
            result = self._execute_live_cascade_strategy(capital)
            if not result['success']:
                return result
            
            # Start monitoring in background
            with self.monitor_lock:
                if not self.monitor_task or not self.monitor_task.is_alive():
                    self.monitor_task = threading.Thread(target=self._background_monitor, daemon=True)
                    self.monitor_task.start()
            
            return {'success': True, 'message': f'🔴 LIVE TRADING STARTED with ${capital}'}
            
        except Exception as e:
            self.logger.error(f"Live trading startup error: {e}")
            return {'success': False, 'error': str(e)}
    
    def _execute_live_cascade_strategy(self, capital: float) -> dict:
        """Execute live cascade strategy with real trades"""
        try:
            current_capital = capital
            
            # Sort assets by safety score (lower volatility preferred for live)
            sorted_assets = sorted(
                self.asset_config.items(),
                key=lambda x: x[1].yield_rate / (1 + x[1].volatility_factor),
                reverse=True
            )
            
            max_levels = min(3, len(sorted_assets))  # Max 3 levels for live trading
            
            for level in range(max_levels):
                if current_capital < 100:  # Minimum position size
                    break
                
                asset_name, asset_config = sorted_assets[level]
                
                try:
                    # Get current price
                    symbol = f"{asset_name}USDT"
                    price_result = self.client.get_symbol_price(symbol)
                    
                    if 'error' in price_result:
                        self.logger.error(f"Failed to get price for {symbol}: {price_result['error']}")
                        continue
                    
                    current_price = float(price_result['price'])
                    
                    # Calculate position size (conservative)
                    max_position = current_capital * 0.8  # Only use 80% of available
                    collateral_usd = min(max_position, current_capital)
                    
                    # Calculate quantity to buy
                    quantity = collateral_usd / current_price
                    
                    # Round quantity to appropriate precision
                    if quantity < 0.001:
                        quantity = round(quantity, 6)
                    elif quantity < 0.1:
                        quantity = round(quantity, 4)
                    else:
                        quantity = round(quantity, 2)
                    
                    self.logger.info(f"Level {level + 1}: Planning to buy {quantity:.6f} {asset_name} at ${current_price}")
                    
                    # Create margin buy order
                    buy_order = self.client.create_margin_order(
                        symbol=symbol,
                        side='BUY',
                        type_='MARKET',
                        quantity=quantity,
                        sideEffectType='MARGIN_BUY'
                    )
                    
                    if 'error' in buy_order:
                        self.logger.error(f"Buy order failed for {asset_name}: {buy_order['error']}")
                        continue
                    
                    self.logger.info(f"✅ Buy order executed for {asset_name}: {buy_order.get('orderId')}")
                    
                    # Calculate maximum borrowable amount
                    actual_collateral = quantity * current_price
                    max_loan = actual_collateral * asset_config.ltv_max
                    
                    # Borrow USDT against the collateral
                    self.logger.info(f"Attempting to borrow ${max_loan:.2f} USDT against {asset_name}")
                    
                    borrow_result = self.client.borrow_margin('USDT', round(max_loan, 2))
                    
                    if 'error' in borrow_result:
                        self.logger.error(f"Borrow failed: {borrow_result['error']}")
                        # Continue without borrowing for this level
                        max_loan = 0
                    else:
                        self.logger.info(f"✅ Borrowed ${max_loan:.2f} USDT successfully")
                    
                    # Create position record
                    position = Position(
                        asset=asset_name,
                        collateral_amount=actual_collateral,
                        loan_amount=max_loan,
                        loan_asset='USDT',
                        current_ltv=max_loan / actual_collateral if actual_collateral > 0 else 0,
                        yield_earned=0,
                        level=level + 1,
                        order_id=buy_order.get('orderId')
                    )
                    
                    self.positions.append(position)
                    self.leveraged_capital += max_loan
                    
                    # Update capital for next level
                    current_capital = max_loan * 0.9 if max_loan > 0 else 0  # Use 90% of borrowed amount
                    
                    self.logger.info(f"✅ Level {level + 1} completed successfully")
                    
                    # Wait between trades to avoid rate limits
                    time.sleep(2)
                    
                except Exception as e:
                    self.logger.error(f"Error in level {level + 1}: {e}")
                    continue
            
            if self.positions:
                self.logger.critical(f"🔴 LIVE STRATEGY DEPLOYED - {len(self.positions)} positions active")
                return {'success': True, 'positions': len(self.positions)}
            else:
                return {'success': False, 'error': 'No positions could be created'}
                
        except Exception as e:
            self.logger.error(f"Live cascade strategy error: {e}")
            return {'success': False, 'error': str(e)}
    
    def _start_demo_trading(self, capital: float) -> dict:
        """Start demo trading simulation"""
        try:
            # Simulate positions
            current_capital = capital
            sorted_assets = sorted(
                self.asset_config.items(),
                key=lambda x: x[1].yield_rate / (1 + x[1].volatility_factor),
                reverse=True
            )
            
            max_levels = min(5, len(sorted_assets))  # Up to 5 levels for demo
            
            for level in range(max_levels):
                if current_capital < 100:
                    break
                
                asset_name, asset_config = sorted_assets[level]
                
                collateral = current_capital * 0.8
                loan_amount = collateral * asset_config.ltv_max
                
                position = Position(
                    asset=asset_name,
                    collateral_amount=collateral,
                    loan_amount=loan_amount,
                    loan_asset='USDT',
                    current_ltv=loan_amount / collateral,
                    yield_earned=0,
                    level=level + 1
                )
                
                self.positions.append(position)
                self.leveraged_capital += loan_amount
                current_capital = loan_amount * 0.9
            
            # Calculate demo yield
            total_net_yield = 0
            for i, position in enumerate(self.positions):
                asset_config = sorted_assets[i][1]
                net_yield_rate = asset_config.yield_rate - asset_config.loan_rate
                total_net_yield += net_yield_rate * position.loan_amount
            
            self.total_yield = (total_net_yield / capital) * 100 if capital > 0 else 0
            
            self.logger.info(f"✅ Demo mode started with {len(self.positions)} positions")
            return {'success': True, 'message': f'📊 DEMO MODE STARTED with ${capital}'}
            
        except Exception as e:
            self.logger.error(f"Demo trading error: {e}")
            return {'success': False, 'error': str(e)}
    
    def _background_monitor(self):
        """Background monitoring task"""
        self.logger.info("Starting background monitoring...")
        
        while self.is_running and not shutdown_flag.is_set():
            try:
                if self.is_live_mode and self.client:
                    # Update positions with real data
                    self._update_live_positions()
                    self._check_margin_health()
                
                self.last_update = datetime.now()
                time.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                self.logger.error(f"Monitor error: {e}")
                time.sleep(60)
        
        self.logger.info("Background monitoring stopped")
    
    def _update_live_positions(self):
        """Update live position data"""
        try:
            for position in self.positions:
                symbol = f"{position.asset}USDT"
                price_result = self.client.get_symbol_price(symbol)
                
                if 'error' not in price_result:
                    current_price = float(price_result['price'])
                    # Update collateral value based on current price
                    current_collateral_qty = position.collateral_amount / current_price
                    current_collateral_value = current_collateral_qty * current_price
                    
                    # Update LTV
                    if current_collateral_value > 0:
                        position.current_ltv = position.loan_amount / current_collateral_value
                    
        except Exception as e:
            self.logger.error(f"Failed to update live positions: {e}")
    
    def _check_margin_health(self):
        """Check margin account health"""
        try:
            account_info = self.client.get_account_info()
            if 'error' not in account_info:
                margin_level = float(account_info.get('marginLevel', 999))
                
                if margin_level < 1.3:
                    self.logger.critical(f"🔴 CRITICAL MARGIN LEVEL: {margin_level}")
                    self._emergency_reduce_positions()
                elif margin_level < 1.5:
                    self.logger.warning(f"⚠️ LOW MARGIN LEVEL: {margin_level}")
                    
        except Exception as e:
            self.logger.error(f"Failed to check margin health: {e}")
    
    def _emergency_reduce_positions(self):
        """Emergency position reduction"""
        self.logger.critical("🔴 EXECUTING EMERGENCY POSITION REDUCTION")
        
        # Sort positions by risk (highest LTV first)
        risky_positions = sorted(self.positions, key=lambda p: p.current_ltv, reverse=True)
        
        for position in risky_positions[:2]:  # Reduce top 2 riskiest
            try:
                # Repay 50% of loan
                repay_amount = position.loan_amount * 0.5
                
                repay_result = self.client.repay_margin('USDT', repay_amount)
                if 'error' not in repay_result:
                    position.loan_amount -= repay_amount
                    position.current_ltv = position.loan_amount / position.collateral_amount
                    self.logger.info(f"✅ Emergency reduced {position.asset} loan by ${repay_amount:.2f}")
                
            except Exception as e:
                self.logger.error(f"Failed to emergency reduce position {position.asset}: {e}")
    
    def stop_bot(self):
        """Stop the bot gracefully"""
        self.logger.info("Stopping bot...")
        self.is_running = False
        self.bot_status = "Stopping"
        
        if self.monitor_task and self.monitor_task.is_alive():
            self.monitor_task.join(timeout=5)
        
        if self.is_live_mode:
            self.logger.info("🔴 Live trading stopped - positions remain open")
            self.bot_status = "Stopped (Positions Open)"
        else:
            self.bot_status = "Stopped"
            self.positions.clear()
    
    def emergency_stop(self):
        """Emergency stop with position closure"""
        self.logger.critical("🔴 EMERGENCY STOP ACTIVATED")
        self.is_running = False
        self.bot_status = "Emergency Stop"
        
        if self.is_live_mode and self.client:
            # Close all positions
            for position in self.positions:
                try:
                    # Repay loan
                    if position.loan_amount > 0:
                        repay_result = self.client.repay_margin('USDT', position.loan_amount)
                        if 'error' in repay_result:
                            self.logger.error(f"Failed to repay loan for {position.asset}: {repay_result['error']}")
                    
                    # Sell collateral
                    symbol = f"{position.asset}USDT"
                    price_result = self.client.get_symbol_price(symbol)
                    
                    if 'error' not in price_result:
                        current_price = float(price_result['price'])
                        quantity = position.collateral_amount / current_price
                        
                        sell_order = self.client.create_margin_order(
                            symbol=symbol,
                            side='SELL',
                            type_='MARKET',
                            quantity=round(quantity, 6),
                            sideEffectType='AUTO_REPAY'
                        )
                        
                        if 'error' not in sell_order:
                            self.logger.info(f"✅ Emergency closed position: {position.asset}")
                        else:
                            self.logger.error(f"Failed to sell {position.asset}: {sell_order['error']}")
                    
                except Exception as e:
                    self.logger.error(f"Failed to emergency close {position.asset}: {e}")
        
        self.positions.clear()
    
    def get_status(self) -> dict:
        """Get current bot status"""
        return {
            'bot_status': self.bot_status,
            'is_live_mode': self.is_live_mode,
            'total_positions': len(self.positions),
            'total_capital': self.total_capital,
            'leveraged_capital': self.leveraged_capital,
            'total_yield': self.total_yield,
            'leverage_ratio': self.leveraged_capital / self.total_capital if self.total_capital > 0 else 0,
            'last_update': self.last_update.strftime('%Y-%m-%d %H:%M:%S'),
            'positions': [
                {
                    'asset': pos.asset,
                    'collateral': round(pos.collateral_amount, 2),
                    'loan': round(pos.loan_amount, 2),
                    'ltv': round(pos.current_ltv * 100, 1),
                    'level': pos.level,
                    'order_id': pos.order_id
                }
                for pos in self.positions
            ]
        }

# Create Flask app
app = Flask(__name__)
bot = None

# HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Live Trading Bot</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            margin: 0; 
            padding: 20px; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }
        .container { 
            max-width: 1200px; 
            margin: 0 auto; 
            background: white; 
            padding: 30px; 
            border-radius: 15px; 
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
        }
        .header { 
            text-align: center; 
            color: #333; 
            margin-bottom: 30px;
            border-bottom: 2px solid #f0f0f0;
            padding-bottom: 20px;
        }
        .header h1 {
            margin: 0;
            font-size: 2.5em;
            background: linear-gradient(45deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .mode-indicator {
            font-size: 1.2em;
            font-weight: bold;
            margin-top: 10px;
            padding: 10px 20px;
            border-radius: 25px;
            display: inline-block;
        }
        .live-mode { background: #ff4757; color: white; }
        .demo-mode { background: #2ed573; color: white; }
        .status { 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px; 
            margin: 30px 0; 
        }
        .metric { 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; 
            padding: 20px; 
            border-radius: 10px; 
            text-align: center;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        .metric h3 { margin: 0 0 10px 0; font-size: 0.9em; opacity: 0.9; }
        .metric .value { font-size: 1.8em; font-weight: bold; }
        .controls { 
            background: #f8f9fa; 
            padding: 25px; 
            border-radius: 10px; 
            margin: 25px 0;
            border-left: 4px solid #667eea;
        }
        .controls h3 { margin-top: 0; color: #333; }
        .input-group { 
            margin: 15px 0; 
            display: flex; 
            align-items: center; 
            gap: 10px;
        }
        .input-group label { 
            font-weight: 500; 
            min-width: 120px;
        }
        .input-group input { 
            padding: 10px 15px; 
            border: 2px solid #ddd; 
            border-radius: 8px; 
            font-size: 16px;
            transition: border-color 0.3s;
        }
        .input-group input:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn { 
            padding: 12px 25px; 
            margin: 8px; 
            border: none; 
            border-radius: 8px; 
            cursor: pointer; 
            font-size: 16px;
            font-weight: 500;
            transition: all 0.3s;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(0,0,0,0.2); }
        .btn-primary { background: #667eea; color: white; }
        .btn-danger { background: #ff4757; color: white; }
        .btn-success { background: #2ed573; color: white; }
        .btn-warning { background: #ffa502; color: white; }
        .positions { 
            margin: 30px 0; 
            background: #f8f9fa; 
            padding: 20px; 
            border-radius: 10px;
        }
        .positions h3 { margin-top: 0; color: #333; }
        table { 
            width: 100%; 
            border-collapse: collapse; 
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        th, td { 
            border: none; 
            padding: 15px; 
            text-align: left; 
        }
        th { 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-weight: 500;
        }
        tbody tr:nth-child(even) { background: #f8f9fa; }
        tbody tr:hover { background: #e3f2fd; }
        .warning { 
            background: linear-gradient(135deg, #ffeaa7 0%, #fab1a0 100%);
            padding: 20px; 
            border-radius: 10px; 
            margin: 25px 0;
            border-left: 4px solid #e17055;
        }
        .warning h4 { margin-top: 0; color: #2d3436; }
        .warning p { color: #2d3436; margin-bottom: 0; }
        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid #f3f3f3;
            border-top: 3px solid #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .status-badge {
            padding: 5px 15px;
            border-radius: 20px;
            color: white;
            font-weight: bold;
            font-size: 0.9em;
        }
        .status-running { background: #2ed573; }
        .status-stopped { background: #747d8c; }
        .status-error { background: #ff4757; }
        .asset-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .asset-card {
            background: white;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .asset-card h4 { margin: 0 0 10px 0; color: #333; }
        .asset-card p { margin: 5px 0; color: #666; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Multi-Asset Leverage Bot</h1>
            <div id="mode-indicator" class="mode-indicator">
                <span class="loading"></span> Loading...
            </div>
        </div>
        
        <div class="controls">
            <h3>🎮 Bot Control Panel</h3>
            <div class="input-group">
                <label for="capital">💰 Initial Capital:</label>
                <input type="number" id="capital" value="1000" min="100" step="100" placeholder="Enter amount in USD">
            </div>
            <div>
                <button class="btn btn-success" onclick="startBot()">🚀 Start Bot</button>
                <button class="btn btn-danger" onclick="stopBot()">⏹️ Stop Bot</button>
                <button class="btn btn-warning" onclick="emergencyStop()">🚨 Emergency Stop</button>
                <button class="btn btn-primary" onclick="updateStatus()">🔄 Refresh Status</button>
            </div>
        </div>
        
        <div class="status">
            <div class="metric">
                <h3>Status</h3>
                <div class="value" id="bot-status">Stopped</div>
            </div>
            <div class="metric">
                <h3>Total Capital</h3>
                <div class="value">$<span id="total-capital">0</span></div>
            </div>
            <div class="metric">
                <h3>Leveraged Capital</h3>
                <div class="value">$<span id="leveraged-capital">0</span></div>
            </div>
            <div class="metric">
                <h3>Estimated Yield</h3>
                <div class="value"><span id="total-yield">0</span>%</div>
            </div>
            <div class="metric">
                <h3>Active Positions</h3>
                <div class="value"><span id="total-positions">0</span></div>
            </div>
        </div>
        
        <div class="positions">
            <h3>📊 Active Positions</h3>
            <table>
                <thead>
                    <tr>
                        <th>Level</th>
                        <th>Asset</th>
                        <th>Collateral</th>
                        <th>Loan Amount</th>
                        <th>LTV Ratio</th>
                        <th>Order ID</th>
                    </tr>
                </thead>
                <tbody id="positions-table">
                    <tr>
                        <td colspan="6" style="text-align: center; color: #666;">No active positions</td>
                    </tr>
                </tbody>
            </table>
        </div>
        
        <div class="positions">
            <h3>⚙️ Asset Configuration</h3>
            <div class="asset-grid" id="asset-config">
                Loading asset configuration...
            </div>
        </div>
        
        <div class="warning">
            <h4>⚠️ Critical Risk Warning</h4>
            <p><strong>Live Trading Mode:</strong> This bot can execute real trades with your money. Leverage trading amplifies both profits and losses. You can lose more than your initial investment. Only use funds you can afford to lose completely.</p>
            <p><strong>Demo Mode:</strong> Safe simulation mode for testing strategies without financial risk.</p>
        </div>
    </div>

    <script>
        let updateInterval;
        
        async function startBot() {
            const capital = parseFloat(document.getElementById('capital').value);
            
            if (capital < 100) {
                alert('Minimum capital is $100');
                return;
            }
            
            const confirmMessage = `Are you sure you want to start the bot with $${capital}? This may involve real money trading.`;
            if (!confirm(confirmMessage)) return;
            
            try {
                const response = await fetch('/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ capital })
                });
                const result = await response.json();
                
                if (result.success) {
                    alert(`✅ ${result.message}`);
                    updateStatus();
                } else {
                    alert(`❌ Error: ${result.error}`);
                }
            } catch (error) {
                alert(`❌ Network Error: ${error.message}`);
            }
        }
        
        async function stopBot() {
            if (!confirm('Are you sure you want to stop the bot?')) return;
            
            try {
                const response = await fetch('/stop', { method: 'POST' });
                const result = await response.json();
                alert(result.success ? `✅ ${result.message}` : `❌ ${result.error}`);
                updateStatus();
            } catch (error) {
                alert(`❌ Error: ${error.message}`);
            }
        }
        
        async function emergencyStop() {
            const confirmMessage = 'EMERGENCY STOP will immediately close all positions and may result in losses. Continue?';
            if (!confirm(confirmMessage)) return;
            
            try {
                const response = await fetch('/emergency_stop', { method: 'POST' });
                const result = await response.json();
                alert(result.success ? '✅ Emergency stop executed' : `❌ ${result.error}`);
                updateStatus();
            } catch (error) {
                alert(`❌ Error: ${error.message}`);
            }
        }
        
        async function updateStatus() {
            try {
                const response = await fetch('/status');
                const data = await response.json();
                
                // Update mode indicator
                const modeDiv = document.getElementById('mode-indicator');
                if (data.is_live_mode) {
                    modeDiv.innerHTML = '🔴 LIVE TRADING MODE';
                    modeDiv.className = 'mode-indicator live-mode';
                } else {
                    modeDiv.innerHTML = '📊 DEMO MODE';
                    modeDiv.className = 'mode-indicator demo-mode';
                }
                
                // Update metrics
                document.getElementById('bot-status').textContent = data.bot_status;
                document.getElementById('total-capital').textContent = data.total_capital.toLocaleString();
                document.getElementById('leveraged-capital').textContent = data.leveraged_capital.toLocaleString();
                document.getElementById('total-yield').textContent = data.total_yield.toFixed(2);
                document.getElementById('total-positions').textContent = data.total_positions;
                
                // Update positions table
                const tbody = document.getElementById('positions-table');
                if (data.positions && data.positions.length > 0) {
                    tbody.innerHTML = data.positions.map(p => `
                        <tr>
                            <td>${p.level}</td>
                            <td><strong>${p.asset}</strong></td>
                            <td>$${p.collateral.toLocaleString()}</td>
                            <td>$${p.loan.toLocaleString()}</td>
                            <td><span class="status-badge ${p.ltv > 70 ? 'status-error' : p.ltv > 50 ? 'status-warning' : 'status-running'}">${p.ltv}%</span></td>
                            <td>${p.order_id || 'N/A'}</td>
                        </tr>
                    `).join('');
                } else {
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #666;">No active positions</td></tr>';
                }
                
            } catch (error) {
                console.error('Status update failed:', error);
                document.getElementById('mode-indicator').innerHTML = '❌ Connection Error';
                document.getElementById('mode-indicator').className = 'mode-indicator status-error';
            }
        }
        
        async function loadAssetConfig() {
            try {
                const response = await fetch('/assets');
                const assets = await response.json();
                const container = document.getElementById('asset-config');
                
                container.innerHTML = Object.entries(assets).map(([symbol, config]) => `
                    <div class="asset-card">
                        <h4>${symbol}</h4>
                        <p><strong>Max LTV:</strong> ${(config.ltv_max * 100).toFixed(0)}%</p>
                        <p><strong>Yield Rate:</strong> ${(config.yield_rate * 100).toFixed(1)}%</p>
                        <p><strong>Loan Rate:</strong> ${(config.loan_rate * 100).toFixed(1)}%</p>
                        <p><strong>Net Yield:</strong> ${((config.yield_rate - config.loan_rate) * 100).toFixed(1)}%</p>
                        <p><strong>Tier:</strong> ${config.liquidity_tier}</p>
                    </div>
                `).join('');
                
            } catch (error) {
                console.error('Failed to load asset config:', error);
                document.getElementById('asset-config').innerHTML = '<p>Failed to load asset configuration</p>';
            }
        }
        
        // Auto-update every 15 seconds when bot is running
        function startAutoUpdate() {
            if (updateInterval) clearInterval(updateInterval);
            updateInterval = setInterval(() => {
                updateStatus();
            }, 15000);
        }
        
        // Initial load
        updateStatus();
        loadAssetConfig();
        startAutoUpdate();
        
        // Cleanup on page unload
        window.addEventListener('beforeunload', () => {
            if (updateInterval) clearInterval(updateInterval);
        });
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    """Main dashboard"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/health')
def health():
    """Railway health check endpoint"""
    return jsonify({
        'status': 'healthy', 
        'timestamp': datetime.now().isoformat(),
        'service': 'live-trading-bot'
    })

@app.route('/start', methods=['POST'])
def start_bot_endpoint():
    """Start the trading bot"""
    global bot
    try:
        data = request.get_json() or {}
        capital = data.get('capital', 1000)
        
        # Get API credentials from environment
        api_key = os.getenv('BINANCE_API_KEY', '').strip()
        api_secret = os.getenv('BINANCE_API_SECRET', '').strip()
        
        # Create bot instance
        bot = LiveTradingBot(api_key, api_secret)
        result = bot.start_bot(capital)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/stop', methods=['POST'])
def stop_bot_endpoint():
    """Stop the trading bot"""
    global bot
    try:
        if bot:
            bot.stop_bot()
            return jsonify({'success': True, 'message': 'Bot stopped successfully'})
        else:
            return jsonify({'success': True, 'message': 'No bot was running'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/emergency_stop', methods=['POST'])
def emergency_stop_endpoint():
    """Emergency stop with position closure"""
    global bot
    try:
        if bot:
            bot.emergency_stop()
            return jsonify({'success': True, 'message': 'Emergency stop executed - all positions closed'})
        else:
            return jsonify({'success': True, 'message': 'No bot was running'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/status')
def get_status_endpoint():
    """Get bot status"""
    global bot
    try:
        if bot:
            return jsonify(bot.get_status())
        else:
            return jsonify({
                'bot_status': 'Not Started',
                'is_live_mode': False,
                'total_positions': 0,
                'total_capital': 0,
                'leveraged_capital': 0,
                'total_yield': 0,
                'leverage_ratio': 0,
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'positions': []
            })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/assets')
def get_assets_endpoint():
    """Get asset configuration"""
    try:
        # Get API credentials to determine mode
        api_key = os.getenv('BINANCE_API_KEY', '').strip()
        api_secret = os.getenv('BINANCE_API_SECRET', '').strip()
        
        temp_bot = LiveTradingBot(api_key, api_secret)
        return jsonify({k: v.__dict__ for k, v in temp_bot.asset_config.items()})
    except Exception as e:
        return jsonify({'error': str(e)})

if __name__ == '__main__':
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # Print startup info
    api_key = os.getenv('BINANCE_API_KEY', '').strip()
    if api_key and api_key != 'demo':
        logger.info("🔴 LIVE TRADING MODE - Real money at risk")
    else:
        logger.info("📊 DEMO MODE - Safe simulation")
    
    try:
        port = int(os.environ.get('PORT', 8080))
        logger.info(f"Starting server on port {port}")
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
    except Exception as e:
        logger.error(f"Application error: {e}")
    finally:
        if bot:
            bot.stop_bot()
        logger.info("Application shutdown complete")