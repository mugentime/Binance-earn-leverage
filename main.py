# live_trading_bot.py - LIVE TRADING VERSION
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
import urllib.parse

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

class LiveBinanceClient:
    """Live Binance API client for margin trading"""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.binance.com"
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
        """Make authenticated request to Binance API"""
        url = f"{self.base_url}{endpoint}"
        
        if params is None:
            params = {}
        
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            query_string = urllib.parse.urlencode(params)
            params['signature'] = self._generate_signature(query_string)
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=self.headers, params=params, timeout=10)
            elif method == 'POST':
                response = requests.post(url, headers=self.headers, params=params, timeout=10)
            elif method == 'DELETE':
                response = requests.delete(url, headers=self.headers, params=params, timeout=10)
            
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.RequestException as e:
            raise Exception(f"API request failed: {e}")
    
    def get_account_info(self) -> dict:
        """Get margin account information"""
        return self._make_request('GET', '/sapi/v1/margin/account', signed=True)
    
    def get_symbol_price(self, symbol: str) -> float:
        """Get current symbol price"""
        response = self._make_request('GET', '/api/v3/ticker/price', {'symbol': symbol})
        return float(response['price'])
    
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
        return [asset for asset in account_info['userAssets'] 
                if float(asset['free']) > 0 or float(asset['locked']) > 0]

class LiveMultiAssetLeverageBot:
    """
    LIVE TRADING Multi-Asset Leverage Bot
    
    ⚠️ CRITICAL WARNING ⚠️
    This bot trades with REAL MONEY and LEVERAGE.
    YOU CAN LOSE MORE THAN YOUR INITIAL INVESTMENT.
    Use at your own risk. Start with small amounts.
    """
    
    def __init__(self, api_key: str, api_secret: str):
        if not api_key or not api_secret or api_key == "demo":
            raise ValueError("LIVE API credentials required. This is not a simulation.")
        
        self.client = LiveBinanceClient(api_key, api_secret)
        
        # Setup logging with more detail for live trading
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('live_trading.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        self.logger.info("🔴 LIVE TRADING BOT INITIALIZED - REAL MONEY AT RISK")
        
        # Asset configuration (conservative for live trading)
        self.asset_config = self._initialize_conservative_config()
        
        # Strategy configuration (more conservative for live)
        self.max_cascade_levels = 3  # Reduced from 5
        self.target_total_leverage = 1.8  # Reduced from 2.4
        self.emergency_ltv = 0.75  # More conservative
        self.rebalance_threshold = 0.03
        
        # Portfolio state
        self.positions: List[Position] = []
        self.total_capital = 0
        self.leveraged_capital = 0
        self.total_yield = 0
        self.is_running = False
        self.bot_status = "Stopped"
        
        # Safety mechanisms
        self.max_daily_loss = 0.05  # 5% max daily loss
        self.circuit_breaker_triggered = False
        self.last_health_check = datetime.now()
    
    def _initialize_conservative_config(self) -> Dict[str, AssetConfig]:
        """Conservative asset config for live trading"""
        return {
            # Only most liquid assets for live trading
            'BTC': AssetConfig('BTC', 0.50, 0.03, 1, 0.02, 0.25),  # Much more conservative
            'ETH': AssetConfig('ETH', 0.45, 0.035, 1, 0.022, 0.28),
            'BNB': AssetConfig('BNB', 0.40, 0.04, 1, 0.025, 0.30),
            'USDC': AssetConfig('USDC', 0.85, 0.02, 1, 0.015, 0.02),  # Stable coin
        }
    
    async def start_live_trading(self, initial_capital: float):
        """Start live trading with real money"""
        try:
            # SAFETY CHECKS
            if initial_capital > 10000:
                raise ValueError("Maximum $10,000 for safety. Increase manually if needed.")
            
            # Verify API connection
            account_info = self.client.get_account_info()
            self.logger.info(f"Connected to Binance account")
            
            # Check account has sufficient balance
            usdt_balance = next((float(asset['free']) for asset in account_info['userAssets'] 
                               if asset['asset'] == 'USDT'), 0)
            
            if usdt_balance < initial_capital:
                raise ValueError(f"Insufficient USDT balance. Have: ${usdt_balance}, Need: ${initial_capital}")
            
            self.total_capital = initial_capital
            self.is_running = True
            self.bot_status = "Running (LIVE)"
            
            self.logger.critical(f"🔴 STARTING LIVE TRADING WITH ${initial_capital}")
            
            # Execute conservative cascade strategy
            await self._execute_live_cascade_strategy(initial_capital)
            
        except Exception as e:
            self.logger.error(f"LIVE TRADING ERROR: {e}")
            self.bot_status = "Error"
            await self.emergency_stop()
            raise
    
    async def _execute_live_cascade_strategy(self, capital: float):
        """Execute live cascade strategy with real trades"""
        current_capital = capital
        
        # Sort assets by safety score (lower volatility preferred for live)
        sorted_assets = sorted(
            self.asset_config.items(),
            key=lambda x: x[1].yield_rate / (1 + x[1].volatility_factor),
            reverse=True
        )
        
        for level in range(min(self.max_cascade_levels, len(sorted_assets))):
            if current_capital < 100:  # Minimum position size
                break
            
            asset_name, asset_config = sorted_assets[level]
            
            try:
                # Get current price
                symbol = f"{asset_name}USDT"
                current_price = self.client.get_symbol_price(symbol)
                
                # Calculate position size (conservative)
                max_position = current_capital * 0.8  # Only use 80% of available
                collateral_usd = min(max_position, current_capital)
                
                # Buy collateral asset
                quantity = collateral_usd / current_price
                
                self.logger.info(f"Level {level + 1}: Buying {quantity:.6f} {asset_name} at ${current_price}")
                
                buy_order = self.client.create_margin_order(
                    symbol=symbol,
                    side='BUY',
                    type_='MARKET',
                    quantity=quantity,
                    sideEffectType='MARGIN_BUY'
                )
                
                # Calculate maximum borrowable amount
                max_loan = collateral_usd * asset_config.ltv_max
                
                # Borrow USDT against the collateral
                self.logger.info(f"Borrowing ${max_loan:.2f} USDT against {asset_name}")
                
                borrow_result = self.client.borrow_margin('USDT', max_loan)
                
                # Create position record
                position = Position(
                    asset=asset_name,
                    collateral_amount=collateral_usd,
                    loan_amount=max_loan,
                    loan_asset='USDT',
                    current_ltv=max_loan / collateral_usd,
                    yield_earned=0,
                    level=level + 1,
                    order_id=buy_order.get('orderId')
                )
                
                self.positions.append(position)
                self.leveraged_capital += max_loan
                
                # Update capital for next level
                current_capital = max_loan * 0.9  # Use 90% of borrowed amount
                
                self.logger.info(f"Level {level + 1} completed successfully")
                
                # Wait between trades to avoid rate limits
                await asyncio.sleep(1)
                
            except Exception as e:
                self.logger.error(f"Error in level {level + 1}: {e}")
                break
        
        self.logger.critical(f"🔴 LIVE STRATEGY DEPLOYED - {len(self.positions)} positions active")
    
    async def monitor_positions(self):
        """Continuously monitor live positions"""
        while self.is_running:
            try:
                await self._health_check()
                await self._update_position_ltv()
                await self._check_emergency_conditions()
                
                # Wait 30 seconds between checks
                await asyncio.sleep(30)
                
            except Exception as e:
                self.logger.error(f"Monitoring error: {e}")
                await asyncio.sleep(60)  # Wait longer on errors
    
    async def _health_check(self):
        """Perform health check on account"""
        try:
            account_info = self.client.get_account_info()
            margin_level = float(account_info['marginLevel'])
            
            self.logger.info(f"Health check - Margin level: {margin_level}")
            
            if margin_level < 1.5:  # Approaching margin call
                self.logger.warning(f"⚠️ LOW MARGIN LEVEL: {margin_level}")
                await self._reduce_positions()
            
            if margin_level < 1.2:  # Critical
                self.logger.critical(f"🔴 CRITICAL MARGIN LEVEL: {margin_level}")
                await self.emergency_stop()
                
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
    
    async def _update_position_ltv(self):
        """Update LTV ratios for all positions"""
        for position in self.positions:
            try:
                symbol = f"{position.asset}USDT"
                current_price = self.client.get_symbol_price(symbol)
                current_value = (position.collateral_amount / current_price) * current_price
                position.current_ltv = position.loan_amount / current_value
                
                if position.current_ltv > self.emergency_ltv:
                    self.logger.warning(f"⚠️ High LTV on {position.asset}: {position.current_ltv:.3f}")
                    
            except Exception as e:
                self.logger.error(f"Failed to update LTV for {position.asset}: {e}")
    
    async def _check_emergency_conditions(self):
        """Check for emergency stop conditions"""
        # Check if any position has dangerous LTV
        dangerous_positions = [p for p in self.positions if p.current_ltv > self.emergency_ltv]
        
        if dangerous_positions:
            self.logger.critical(f"🔴 EMERGENCY: {len(dangerous_positions)} positions over safety limit")
            await self.emergency_stop()
    
    async def _reduce_positions(self):
        """Reduce position sizes to improve margin"""
        self.logger.info("Reducing positions to improve margin safety")
        
        # Sort positions by risk (highest LTV first)
        risky_positions = sorted(self.positions, key=lambda p: p.current_ltv, reverse=True)
        
        for position in risky_positions[:2]:  # Reduce top 2 riskiest
            try:
                # Repay 25% of loan
                repay_amount = position.loan_amount * 0.25
                
                self.client.repay_margin('USDT', repay_amount)
                position.loan_amount -= repay_amount
                position.current_ltv = position.loan_amount / position.collateral_amount
                
                self.logger.info(f"Reduced {position.asset} loan by ${repay_amount:.2f}")
                
            except Exception as e:
                self.logger.error(f"Failed to reduce position {position.asset}: {e}")
    
    async def emergency_stop(self):
        """Emergency stop all trading"""
        self.logger.critical("🔴 EMERGENCY STOP ACTIVATED")
        self.is_running = False
        self.bot_status = "Emergency Stop"
        self.circuit_breaker_triggered = True
        
        # Close all positions
        for position in self.positions:
            try:
                # Repay loan
                self.client.repay_margin('USDT', position.loan_amount)
                
                # Sell collateral
                symbol = f"{position.asset}USDT"
                current_price = self.client.get_symbol_price(symbol)
                quantity = position.collateral_amount / current_price
                
                self.client.create_margin_order(
                    symbol=symbol,
                    side='SELL',
                    type_='MARKET',
                    quantity=quantity,
                    sideEffectType='AUTO_REPAY'
                )
                
                self.logger.info(f"Emergency closed position: {position.asset}")
                
            except Exception as e:
                self.logger.error(f"Failed to emergency close {position.asset}: {e}")
        
        self.positions.clear()
    
    def stop_bot(self):
        """Gracefully stop the bot"""
        self.logger.info("Stopping bot gracefully...")
        self.is_running = False
        self.bot_status = "Stopping"
        
        # This should trigger position closure in the main loop
    
    def get_portfolio_status(self) -> Dict:
        """Get current portfolio status"""
        try:
            account_info = self.client.get_account_info()
            total_asset_btc = float(account_info['totalAssetOfBtc'])
            margin_level = float(account_info['marginLevel'])
            
            return {
                'bot_status': self.bot_status,
                'total_positions': len(self.positions),
                'total_capital': self.total_capital,
                'leveraged_capital': self.leveraged_capital,
                'margin_level': margin_level,
                'total_asset_btc': total_asset_btc,
                'leverage_ratio': self.leveraged_capital / self.total_capital if self.total_capital > 0 else 0,
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'circuit_breaker': self.circuit_breaker_triggered,
                'positions': [
                    {
                        'asset': pos.asset,
                        'collateral': pos.collateral_amount,
                        'loan': pos.loan_amount,
                        'ltv': pos.current_ltv,
                        'level': pos.level,
                        'order_id': pos.order_id
                    }
                    for pos in self.positions
                ]
            }
        except Exception as e:
            self.logger.error(f"Failed to get portfolio status: {e}")
            return {'error': str(e)}

# Flask app for live trading
app = Flask(__name__)
live_bot = None

@app.route('/start_live', methods=['POST'])
def start_live_trading():
    global live_bot
    try:
        data = request.get_json()
        capital = data.get('capital', 1000)  # Default smaller for safety
        
        # Get real API credentials from environment
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        
        if not api_key or not api_secret:
            return jsonify({
                'success': False, 
                'error': 'BINANCE_API_KEY and BINANCE_API_SECRET environment variables required'
            })
        
        # Create live bot instance
        live_bot = LiveMultiAssetLeverageBot(api_key, api_secret)
        
        # Start trading in background thread
        import threading
        def run_live_trading():
            asyncio.run(live_bot.start_live_trading(capital))
            # Start monitoring
            asyncio.run(live_bot.monitor_positions())
        
        thread = threading.Thread(target=run_live_trading)
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'message': f'🔴 LIVE TRADING STARTED with ${capital}'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/emergency_stop', methods=['POST'])
def emergency_stop():
    global live_bot
    try:
        if live_bot:
            asyncio.run(live_bot.emergency_stop())
        return jsonify({'success': True, 'message': 'Emergency stop executed'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/live_status')
def live_status():
    global live_bot
    if live_bot:
        return jsonify(live_bot.get_portfolio_status())
    else:
        return jsonify({'error': 'No live bot running'})

if __name__ == '__main__':
    print("🔴 LIVE TRADING BOT - REAL MONEY AT RISK")
    print("Set BINANCE_API_KEY and BINANCE_API_SECRET environment variables")
    print("Use /start_live endpoint to begin trading")
    
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)