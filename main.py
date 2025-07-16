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
    order_id: str = None
    margin_transferred: bool = False
    savings_deposited: bool = False

class BinanceAPI:
    """Complete Binance API for real trading"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://testnet.binance.vision" if testnet else "https://api.binance.com"
        self.headers = {'X-MBX-APIKEY': api_key}
        self.logger = logging.getLogger(__name__)
        
        self.public_endpoints = {
            '/api/v3/ping',
            '/api/v3/time',
            '/api/v3/ticker/price',
            '/api/v3/exchangeInfo'
        }
    
    def _generate_signature(self, query_string: str) -> str:
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _make_request(self, endpoint: str, params: Dict = None, method: str = 'GET', require_auth: bool = None) -> Dict:
        if params is None:
            params = {}
        
        if require_auth is None:
            require_auth = endpoint not in self.public_endpoints
        
        if require_auth:
            params['timestamp'] = int(time.time() * 1000)
            query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            params['signature'] = self._generate_signature(query_string)
            headers = self.headers
        else:
            headers = {}
        
        try:
            self.logger.info(f"🔄 {method} {endpoint}")
            
            if method == 'GET':
                response = requests.get(f"{self.base_url}{endpoint}", params=params, headers=headers, timeout=15)
            elif method == 'POST':
                response = requests.post(f"{self.base_url}{endpoint}", params=params, headers=headers, timeout=15)
            elif method == 'DELETE':
                response = requests.delete(f"{self.base_url}{endpoint}", params=params, headers=headers, timeout=15)
            
            if response.status_code == 200:
                result = response.json()
                self.logger.info(f"✅ {endpoint} success")
                return result
            else:
                error_msg = response.text
                self.logger.error(f"❌ {endpoint} failed: {response.status_code} - {error_msg}")
                return {"error": f"HTTP {response.status_code}", "message": error_msg}
                
        except Exception as e:
            self.logger.error(f"❌ {endpoint} exception: {str(e)}")
            return {"error": "exception", "message": str(e)}
    
    def get_account_info(self) -> Dict:
        return self._make_request("/api/v3/account", require_auth=True)
    
    def get_symbol_price(self, symbol: str) -> Dict:
        return self._make_request("/api/v3/ticker/price", {"symbol": symbol}, require_auth=False)
    
    def get_all_prices(self) -> List[Dict]:
        result = self._make_request("/api/v3/ticker/price", require_auth=False)
        return result if isinstance(result, list) else []
    
    def get_exchange_info(self) -> Dict:
        return self._make_request("/api/v3/exchangeInfo", require_auth=False)
    
    def place_order(self, symbol: str, side: str, order_type: str, quantity: float, **kwargs) -> Dict:
        """Place a real market order"""
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': f"{quantity:.8f}".rstrip('0').rstrip('.')
        }
        params.update(kwargs)
        self.logger.info(f"🔥 PLACING REAL ORDER: {side} {quantity} {symbol}")
        return self._make_request("/api/v3/order", params, method='POST', require_auth=True)
    
    def get_order_status(self, symbol: str, order_id: str) -> Dict:
        return self._make_request("/api/v3/order", {
            'symbol': symbol,
            'orderId': order_id
        }, require_auth=True)
    
    def get_margin_account(self) -> Dict:
        return self._make_request("/sapi/v1/margin/account", require_auth=True)
    
    def margin_borrow(self, asset: str, amount: float) -> Dict:
        """Execute real margin borrow"""
        params = {
            'asset': asset,
            'amount': f"{amount:.8f}".rstrip('0').rstrip('.')
        }
        self.logger.info(f"💰 REAL MARGIN BORROW: {amount} {asset}")
        return self._make_request("/sapi/v1/margin/loan", params, method='POST', require_auth=True)
    
    def margin_repay(self, asset: str, amount: float) -> Dict:
        """Execute real margin repay"""
        params = {
            'asset': asset,
            'amount': f"{amount:.8f}".rstrip('0').rstrip('.')
        }
        self.logger.info(f"💸 REAL MARGIN REPAY: {amount} {asset}")
        return self._make_request("/sapi/v1/margin/repay", params, method='POST', require_auth=True)
    
    def transfer_to_margin(self, asset: str, amount: float) -> Dict:
        """Transfer assets to margin account"""
        params = {
            'asset': asset,
            'amount': f"{amount:.8f}".rstrip('0').rstrip('.'),
            'type': 1  # MAIN_MARGIN
        }
        self.logger.info(f"📤 TRANSFER TO MARGIN: {amount} {asset}")
        return self._make_request("/sapi/v1/margin/transfer", params, method='POST', require_auth=True)
    
    def transfer_from_margin(self, asset: str, amount: float) -> Dict:
        """Transfer assets from margin account"""
        params = {
            'asset': asset,
            'amount': f"{amount:.8f}".rstrip('0').rstrip('.'),
            'type': 2  # MARGIN_MAIN
        }
        self.logger.info(f"📥 TRANSFER FROM MARGIN: {amount} {asset}")
        return self._make_request("/sapi/v1/margin/transfer", params, method='POST', require_auth=True)

class MultiAssetLeverageBot:
    """REAL TRADING BOT - Executes actual trades"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        
        # Enhanced logging for real trading
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Initialize API
        self.binance_api = BinanceAPI(api_key, api_secret, testnet)
        
        # Trading configuration - REAL STRATEGY
        self.asset_config = self._initialize_asset_config()
        self.max_cascade_levels = 3  # Start with 3 levels for safety
        self.target_total_leverage = 2.0
        self.emergency_ltv = 0.85
        
        # Portfolio state
        self.positions: List[Position] = []
        self.total_capital = 0
        self.leveraged_capital = 0
        self.total_yield = 0
        
        # Control state
        self.is_running = False
        self.bot_status = "Stopped"
        self.price_cache = {}
        
        # Load initial price cache
        self._update_price_cache()
    
    def _initialize_asset_config(self) -> Dict[str, AssetConfig]:
        """Asset configuration for real trading - conservative settings"""
        return {
            # Conservative Tier 1 - High liquidity, lower LTV for safety
            'BTC': AssetConfig('BTC', 0.60, 0.04, 1, 0.025, 0.25),
            'ETH': AssetConfig('ETH', 0.55, 0.05, 1, 0.028, 0.30),
            'BNB': AssetConfig('BNB', 0.50, 0.06, 1, 0.030, 0.35),
            
            # Tier 2 - Medium liquidity
            'ADA': AssetConfig('ADA', 0.45, 0.08, 2, 0.035, 0.50),
            'DOT': AssetConfig('DOT', 0.40, 0.09, 2, 0.038, 0.55),
            'LINK': AssetConfig('LINK', 0.35, 0.10, 2, 0.040, 0.60),
        }
    
    def _update_price_cache(self):
        """Load current prices"""
        try:
            all_prices = self.binance_api.get_all_prices()
            if all_prices:
                self.price_cache = {p['symbol']: float(p['price']) for p in all_prices}
                self.logger.info(f"📊 Price cache updated: {len(self.price_cache)} pairs")
        except Exception as e:
            self.logger.error(f"Error updating prices: {e}")
    
    def _get_asset_price(self, asset: str) -> float:
        """Get current asset price"""
        if asset == 'USDT':
            return 1.0
        
        symbol = f"{asset}USDT"
        if symbol in self.price_cache:
            return self.price_cache[symbol]
        
        # Fallback API call
        price_data = self.binance_api.get_symbol_price(symbol)
        if "price" in price_data:
            price = float(price_data['price'])
            self.price_cache[symbol] = price
            return price
        
        return 0.0
    
    def _get_symbol_info(self, symbol: str) -> Dict:
        """Get trading symbol information for proper quantity formatting"""
        try:
            exchange_info = self.binance_api.get_exchange_info()
            if "symbols" in exchange_info:
                for s in exchange_info["symbols"]:
                    if s["symbol"] == symbol:
                        return s
        except Exception as e:
            self.logger.error(f"Error getting symbol info: {e}")
        return {}
    
    def _format_quantity(self, symbol: str, quantity: float) -> float:
        """Format quantity according to symbol requirements"""
        symbol_info = self._get_symbol_info(symbol)
        if symbol_info:
            for filter_item in symbol_info.get("filters", []):
                if filter_item["filterType"] == "LOT_SIZE":
                    step_size = float(filter_item["stepSize"])
                    # Round down to step size
                    return float(int(quantity / step_size) * step_size)
        
        # Default to 6 decimal places
        return round(quantity, 6)
    
    async def start_trading(self, initial_capital: float):
        """Start REAL trading with actual strategy execution"""
        try:
            self.logger.info(f"🚀 STARTING REAL TRADING WITH ${initial_capital}")
            
            # Validate account
            account_info = self.binance_api.get_account_info()
            if "error" in account_info:
                raise Exception(f"Account error: {account_info['message']}")
            
            # Check USDT balance
            usdt_balance = 0
            for balance in account_info.get('balances', []):
                if balance['asset'] == 'USDT':
                    usdt_balance = float(balance['free'])
                    break
            
            if usdt_balance < initial_capital:
                raise Exception(f"Insufficient USDT: Available ${usdt_balance}, Need ${initial_capital}")
            
            self.total_capital = initial_capital
            self.is_running = True
            self.bot_status = "Executing Strategy"
            
            # Execute the REAL cascade strategy
            self.logger.info("🔥 EXECUTING REAL TRADING STRATEGY")
            await self._execute_cascade_strategy(initial_capital)
            
            self.bot_status = "Active Trading"
            self.logger.info("✅ REAL TRADING STRATEGY EXECUTED SUCCESSFULLY")
            
        except Exception as e:
            self.logger.error(f"❌ TRADING FAILED: {e}")
            self.bot_status = "Error"
            raise
    
    async def _execute_cascade_strategy(self, capital: float):
        """Execute REAL cascade leverage strategy"""
        try:
            current_capital = capital
            
            # Sort assets by safety (reverse volatility)
            sorted_assets = sorted(
                [(k, v) for k, v in self.asset_config.items()],
                key=lambda x: x[1].volatility_factor  # Lower volatility first
            )
            
            self.logger.info(f"🎯 EXECUTING {self.max_cascade_levels} LEVEL CASCADE")
            
            for level in range(self.max_cascade_levels):
                if current_capital < 20:  # Minimum $20
                    self.logger.warning(f"Capital too low: ${current_capital}")
                    break
                
                if level >= len(sorted_assets):
                    break
                
                asset_name, asset_config = sorted_assets[level]
                
                # Conservative loan calculation
                max_loan = current_capital * asset_config.ltv_max * 0.90  # 10% safety buffer
                
                self.logger.info(f"🔄 LEVEL {level + 1}: {asset_name} with ${current_capital:.2f}")
                
                # Execute the cascade level with REAL TRADES
                success = await self._execute_cascade_level(
                    level + 1, asset_name, current_capital, max_loan
                )
                
                if success:
                    current_capital = max_loan
                    self.leveraged_capital += max_loan
                    self.logger.info(f"✅ LEVEL {level + 1} SUCCESS - New capital: ${current_capital:.2f}")
                else:
                    self.logger.error(f"❌ LEVEL {level + 1} FAILED - Stopping cascade")
                    break
                    
                # Wait between levels
                await asyncio.sleep(2)
            
            self.logger.info(f"🎉 CASCADE COMPLETE - Total leveraged: ${self.leveraged_capital:.2f}")
                    
        except Exception as e:
            self.logger.error(f"❌ CASCADE STRATEGY FAILED: {e}")
            raise
    
    async def _execute_cascade_level(self, level: int, asset: str, collateral_amount: float, 
                                   loan_amount: float) -> bool:
        """Execute REAL trading for one cascade level"""
        try:
            self.logger.info(f"🔥 EXECUTING REAL LEVEL {level}: {asset}")
            self.logger.info(f"💰 Collateral: ${collateral_amount:.2f} | Loan Target: ${loan_amount:.2f}")
            
            # 1. GET CURRENT PRICE
            asset_price = self._get_asset_price(asset)
            if asset_price <= 0:
                self.logger.error(f"❌ Invalid price for {asset}")
                return False
            
            self.logger.info(f"💲 {asset} price: ${asset_price:.6f}")
            
            # 2. CALCULATE PURCHASE QUANTITY
            symbol = f"{asset}USDT"
            raw_quantity = collateral_amount / asset_price
            quantity = self._format_quantity(symbol, raw_quantity)
            
            self.logger.info(f"🛒 Buying {quantity} {asset} (${quantity * asset_price:.2f})")
            
            # 3. PLACE REAL BUY ORDER
            buy_order = self.binance_api.place_order(
                symbol=symbol,
                side='BUY',
                order_type='MARKET',
                quantity=quantity
            )
            
            if "error" in buy_order:
                self.logger.error(f"❌ BUY ORDER FAILED: {buy_order['message']}")
                return False
            
            order_id = buy_order.get('orderId', 'N/A')
            self.logger.info(f"✅ BUY ORDER EXECUTED - ID: {order_id}")
            
            # Wait for order execution
            await asyncio.sleep(1)
            
            # 4. TRANSFER TO MARGIN ACCOUNT
            self.logger.info(f"📤 Transferring {quantity} {asset} to margin...")
            transfer_result = self.binance_api.transfer_to_margin(asset, quantity)
            
            if "error" in transfer_result:
                self.logger.error(f"❌ MARGIN TRANSFER FAILED: {transfer_result['message']}")
                return False
            
            self.logger.info(f"✅ MARGIN TRANSFER SUCCESSFUL")
            
            # Wait for transfer
            await asyncio.sleep(2)
            
            # 5. BORROW USDT AGAINST COLLATERAL
            self.logger.info(f"💰 Borrowing ${loan_amount:.2f} USDT against {asset}...")
            borrow_result = self.binance_api.margin_borrow('USDT', loan_amount)
            
            if "error" in borrow_result:
                self.logger.error(f"❌ MARGIN BORROW FAILED: {borrow_result['message']}")
                return False
            
            self.logger.info(f"✅ BORROWED ${loan_amount:.2f} USDT")
            
            # Wait for borrow
            await asyncio.sleep(2)
            
            # 6. TRANSFER BORROWED USDT TO SPOT FOR NEXT LEVEL
            self.logger.info(f"📥 Transferring borrowed USDT to spot...")
            transfer_back = self.binance_api.transfer_from_margin('USDT', loan_amount)
            
            if "error" in transfer_back:
                self.logger.error(f"❌ USDT TRANSFER FAILED: {transfer_back['message']}")
                # Not critical - we can continue
            else:
                self.logger.info(f"✅ USDT TRANSFERRED TO SPOT")
            
            # 7. CREATE POSITION RECORD
            current_ltv = loan_amount / (quantity * asset_price)
            
            position = Position(
                asset=asset,
                collateral_amount=quantity,
                loan_amount=loan_amount,
                loan_asset='USDT',
                current_ltv=current_ltv,
                yield_earned=0,
                level=level,
                order_id=order_id,
                margin_transferred=True,
                savings_deposited=False
            )
            
            self.positions.append(position)
            
            self.logger.info(f"🎯 POSITION CREATED: Level {level} | {asset} | LTV: {current_ltv:.1%}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ LEVEL {level} EXECUTION FAILED: {e}")
            return False
    
    def stop_trading(self):
        """Stop trading and liquidate positions"""
        try:
            self.logger.info("🛑 STOPPING TRADING - LIQUIDATING POSITIONS")
            self.is_running = False
            self.bot_status = "Liquidating"
            
            # Liquidate all positions in reverse order
            for position in reversed(self.positions):
                self._liquidate_position(position)
            
            self.positions.clear()
            self.leveraged_capital = 0
            self.total_yield = 0
            self.bot_status = "Stopped"
            
            self.logger.info("✅ ALL POSITIONS LIQUIDATED")
            
        except Exception as e:
            self.logger.error(f"❌ LIQUIDATION ERROR: {e}")
            self.bot_status = "Error"
    
    def _liquidate_position(self, position: Position):
        """Liquidate a single position"""
        try:
            self.logger.info(f"💥 LIQUIDATING: {position.asset} Level {position.level}")
            
            # 1. Sell the collateral asset
            symbol = f"{position.asset}USDT"
            sell_order = self.binance_api.place_order(
                symbol=symbol,
                side='SELL',
                order_type='MARKET',
                quantity=position.collateral_amount
            )
            
            if "error" not in sell_order:
                self.logger.info(f"✅ SOLD {position.asset} - Order: {sell_order.get('orderId')}")
                
                # 2. Repay the loan
                time.sleep(2)  # Wait for sell order
                repay_result = self.binance_api.margin_repay('USDT', position.loan_amount)
                
                if "error" not in repay_result:
                    self.logger.info(f"✅ REPAID ${position.loan_amount:.2f} USDT")
                else:
                    self.logger.error(f"❌ REPAY FAILED: {repay_result['message']}")
            else:
                self.logger.error(f"❌ SELL FAILED: {sell_order['message']}")
                
        except Exception as e:
            self.logger.error(f"❌ LIQUIDATION FAILED: {e}")
    
    def get_portfolio_status(self) -> Dict:
        """Get current portfolio status"""
        total_collateral_value = 0
        total_loan_value = 0
        
        for position in self.positions:
            asset_price = self._get_asset_price(position.asset)
            total_collateral_value += position.collateral_amount * asset_price
            total_loan_value += position.loan_amount
        
        net_value = total_collateral_value - total_loan_value
        leverage_ratio = total_loan_value / self.total_capital if self.total_capital > 0 else 0
        
        # Calculate estimated yield
        annual_yield = 0
        for position in self.positions:
            asset_config = self.asset_config.get(position.asset)
            if asset_config:
                net_rate = asset_config.yield_rate - asset_config.loan_rate
                annual_yield += net_rate * position.loan_amount
        
        roi_percentage = (annual_yield / self.total_capital * 100) if self.total_capital > 0 else 0
        
        return {
            'bot_status': self.bot_status,
            'total_positions': len(self.positions),
            'total_capital': self.total_capital,
            'leveraged_capital': total_loan_value,
            'net_portfolio_value': net_value,
            'total_yield': roi_percentage,
            'leverage_ratio': leverage_ratio,
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'positions': [
                {
                    'level': pos.level,
                    'asset': pos.asset,
                    'collateral': pos.collateral_amount,
                    'loan': pos.loan_amount,
                    'ltv': pos.current_ltv,
                    'usd_value': pos.collateral_amount * self._get_asset_price(pos.asset),
                    'order_id': pos.order_id
                }
                for pos in self.positions
            ]
        }
    
    def get_account_balances(self) -> Dict:
        """Get account balances"""
        try:
            account_info = self.binance_api.get_account_info()
            if "error" in account_info:
                return {'total_usd_value': 0, 'balances': {}, 'error': account_info['message']}
            
            balances = {}
            total_usd = 0
            
            for balance in account_info.get('balances', []):
                asset = balance['asset']
                free = float(balance['free'])
                locked = float(balance['locked'])
                total = free + locked
                
                if total > 0.001:
                    price = self._get_asset_price(asset)
                    if price > 0:
                        usd_value = total * price
                        total_usd += usd_value
                        
                        balances[asset] = {
                            'spot_free': free,
                            'spot_locked': locked,
                            'spot_total': total,
                            'price': price,
                            'usd_value': usd_value
                        }
            
            return {
                'total_usd_value': total_usd,
                'balances': balances,
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
        except Exception as e:
            return {'total_usd_value': 0, 'balances': {}, 'error': str(e)}

# Global bot instance
bot = None

# Flask Application
app = Flask(__name__)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Multi-Asset Leverage Bot - REAL TRADING EXECUTION</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 0; background: #f5f5f5; }
        
        .trading-banner {
            background: linear-gradient(135deg, #dc3545, #fd7e14);
            color: white;
            padding: 15px 20px;
            text-align: center;
            font-weight: bold;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.9; }
        }
        
        .container { 
            max-width: 1200px; 
            margin: 20px auto; 
            background: white; 
            padding: 20px; 
            border-radius: 10px; 
            box-shadow: 0 0 10px rgba(0,0,0,0.1); 
        }
        
        .header { text-align: center; color: #333; margin-bottom: 30px; }
        .controls { background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px; border: 2px solid #dc3545; }
        .status { display: flex; justify-content: space-between; margin-bottom: 20px; }
        .metric { background: #007bff; color: white; padding: 15px; border-radius: 8px; text-align: center; flex: 1; margin: 0 5px; }
        .metric.yield { background: #28a745; }
        .metric.leverage { background: #ffc107; color: #333; }
        .metric.positions { background: #17a2b8; }
        .metric.net-value { background: #6f42c1; }
        
        .positions-table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        .positions-table th, .positions-table td { border: 1px solid #ddd; padding: 12px; text-align: left; }
        .positions-table th { background: #f8f9fa; }
        
        .btn { padding: 10px 20px; margin: 5px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; }
        .btn-primary { background: #007bff; color: white; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-success { background: #28a745; color: white; }
        
        .input-group { margin: 10px 0; }
        .input-group label { display: block; margin-bottom: 5px; font-weight: bold; }
        .input-group input { width: 200px; padding: 8px; border: 1px solid #ddd; border-radius: 4px; }
        
        .status-indicator { padding: 5px 10px; border-radius: 20px; color: white; font-weight: bold; }
        .status-running { background: #28a745; }
        .status-stopped { background: #dc3545; }
        .status-executing { background: #ffc107; color: #333; }
        .status-error { background: #dc3545; }
        
        .trading-warning {
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            padding: 15px;
            border-radius: 8px;
            margin: 10px 0;
            font-weight: bold;
        }
        
        .balances-section {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 20px;
        }
        
        .balance-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .balance-item {
            background: rgba(255,255,255,0.1);
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
        
        .balance-label {
            font-size: 12px;
            opacity: 0.9;
            margin-bottom: 5px;
            text-transform: uppercase;
        }
        
        .balance-value {
            font-size: 18px;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="trading-banner">
        🔥 REAL TRADING EXECUTION - ACTUAL ORDERS & POSITIONS
    </div>

    <div class="container">
        <div class="header">
            <h1>🔥 Multi-Asset Leverage Bot - REAL EXECUTION</h1>
            <p><strong>Executes Real Trades, Orders, Borrowing & Lending</strong></p>
        </div>
        
        <div class="balances-section">
            <h3>💼 Live Account Status</h3>
            <div class="balance-grid">
                <div class="balance-item">
                    <div class="balance-label">Available USDT</div>
                    <div class="balance-value">$<span id="available-usdt">0.00</span></div>
                </div>
                <div class="balance-item">
                    <div class="balance-label">Active Positions</div>
                    <div class="balance-value"><span id="position-count">0</span></div>
                </div>
                <div class="balance-item">
                    <div class="balance-label">Total Loans</div>
                    <div class="balance-value">$<span id="total-loans">0.00</span></div>
                </div>
                <div class="balance-item">
                    <div class="balance-label">Net Portfolio</div>
                    <div class="balance-value">$<span id="net-portfolio">0.00</span></div>
                </div>
            </div>
        </div>
        
        <div class="controls">
            <h3>🔥 Real Trading Execution</h3>
            <div class="trading-warning">
                ⚠️ WARNING: This will execute REAL trades with REAL money. Orders will be placed immediately.
            </div>
            <div class="input-group">
                <label for="capital">Capital to Deploy (USD):</label>
                <input type="number" id="capital" value="50" min="20" step="10">
            </div>
            <button class="btn btn-danger" onclick="startRealTrading()">🔥 EXECUTE REAL TRADING</button>
            <button class="btn btn-danger" onclick="stopTrading()">🛑 LIQUIDATE ALL POSITIONS</button>
            <button class="btn btn-primary" onclick="updateStatus()">🔄 Refresh Status</button>
        </div>
        
        <div class="status" id="status">
            <div class="metric">
                <div>Bot Status</div>
                <div><span id="bot-status" class="status-indicator status-stopped">Stopped</span></div>
            </div>
            <div class="metric">
                <div>Deployed Capital</div>
                <div>$<span id="total-capital">0</span></div>
            </div>
            <div class="metric leverage">
                <div>Total Leveraged</div>
                <div>$<span id="leveraged-capital">0</span></div>
            </div>
            <div class="metric net-value">
                <div>Net Value</div>
                <div>$<span id="net-value">0</span></div>
            </div>
            <div class="metric yield">
                <div>Est. Annual ROI</div>
                <div><span id="total-yield">0</span>%</div>
            </div>
        </div>
        
        <div>
            <h3>📊 Live Trading Positions</h3>
            <table class="positions-table" id="positions-table">
                <thead>
                    <tr>
                        <th>Level</th>
                        <th>Asset</th>
                        <th>Collateral</th>
                        <th>Loan (USDT)</th>
                        <th>LTV</th>
                        <th>USD Value</th>
                        <th>Order ID</th>
                    </tr>
                </thead>
                <tbody id="positions-body">
                    <tr>
                        <td colspan="7" style="text-align: center; color: #666;">No active positions</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <script>
        let isTrading = false;
        
        async function startRealTrading() {
            if (isTrading) return;
            
            const capital = document.getElementById('capital').value;
            
            if (!confirm(`EXECUTE REAL TRADING with $${capital}?\\n\\nThis will:\\n- Place real market orders\\n- Borrow real money\\n- Create leveraged positions\\n\\nContinue?`)) {
                return;
            }
            
            if (!confirm('FINAL CONFIRMATION:\\n\\nThis is LIVE TRADING with REAL MONEY.\\nReal orders will be executed immediately.\\n\\nProceed?')) {
                return;
            }
            
            isTrading = true;
            
            try {
                const response = await fetch('/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ capital: parseFloat(capital) })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    alert('✅ REAL TRADING STARTED! Check positions table for live updates.');
                    setTimeout(updateStatus, 2000);
                } else {
                    alert(`❌ Trading failed: ${result.error}`);
                }
            } catch (error) {
                alert(`❌ Network error: ${error.message}`);
            } finally {
                isTrading = false;
            }
        }
        
        async function stopTrading() {
            if (!confirm('LIQUIDATE ALL POSITIONS?\\n\\nThis will sell all assets and repay all loans.')) {
                return;
            }
            
            try {
                const response = await fetch('/stop', { method: 'POST' });
                const result = await response.json();
                alert('🛑 All positions liquidated');
                setTimeout(updateStatus, 2000);
            } catch (error) {
                alert(`❌ Error: ${error.message}`);
            }
        }
        
        async function updateStatus() {
            try {
                const [statusResponse, balanceResponse] = await Promise.all([
                    fetch('/status'),
                    fetch('/balances')
                ]);
                
                const statusData = await statusResponse.json();
                const balanceData = await balanceResponse.json();
                
                // Update metrics
                document.getElementById('total-capital').textContent = statusData.total_capital.toLocaleString();
                document.getElementById('leveraged-capital').textContent = statusData.leveraged_capital.toLocaleString();
                document.getElementById('net-value').textContent = statusData.net_portfolio_value.toLocaleString();
                document.getElementById('total-yield').textContent = statusData.total_yield.toFixed(2);
                document.getElementById('position-count').textContent = statusData.total_positions;
                
                // Update bot status
                const statusElement = document.getElementById('bot-status');
                statusElement.textContent = statusData.bot_status;
                statusElement.className = 'status-indicator status-' + statusData.bot_status.toLowerCase().replace(' ', '-');
                
                // Update available USDT
                const usdtBalance = balanceData.balances['USDT'];
                if (usdtBalance) {
                    document.getElementById('available-usdt').textContent = usdtBalance.spot_free.toLocaleString(undefined, {minimumFractionDigits: 2});
                }
                
                // Update total loans
                document.getElementById('total-loans').textContent = statusData.leveraged_capital.toLocaleString();
                document.getElementById('net-portfolio').textContent = statusData.net_portfolio_value.toLocaleString();
                
                // Update positions table
                const tbody = document.getElementById('positions-body');
                tbody.innerHTML = '';
                
                if (statusData.positions.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #666;">No active positions</td></tr>';
                } else {
                    statusData.positions.forEach(pos => {
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td><strong>Level ${pos.level}</strong></td>
                            <td><strong>${pos.asset}</strong></td>
                            <td>${pos.collateral.toFixed(6)}</td>
                            <td>$${pos.loan.toLocaleString()}</td>
                            <td><strong>${(pos.ltv * 100).toFixed(1)}%</strong></td>
                            <td>$${pos.usd_value.toLocaleString()}</td>
                            <td><code>${pos.order_id || 'N/A'}</code></td>
                        `;
                        tbody.appendChild(row);
                    });
                }
            } catch (error) {
                console.error('Error updating status:', error);
            }
        }
        
        // Auto-refresh every 10 seconds
        setInterval(updateStatus, 10000);
        
        // Initial load
        updateStatus();
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/start', methods=['POST'])
def start_trading():
    global bot
    try:
        data = request.get_json()
        capital = data.get('capital', 50)
        
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        testnet = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'
        
        if not api_key or not api_secret:
            return jsonify({'success': False, 'error': 'API credentials not configured'})
        
        # Create new bot instance
        bot = MultiAssetLeverageBot(api_key, api_secret, testnet)
        
        # Start real trading in background
        def start_async():
            asyncio.run(bot.start_trading(capital))
        
        thread = threading.Thread(target=start_async)
        thread.start()
        
        return jsonify({'success': True, 'message': 'Real trading strategy executing'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/stop', methods=['POST'])
def stop_trading():
    global bot
    try:
        if bot:
            bot.stop_trading()
        return jsonify({'success': True, 'message': 'All positions liquidated'})
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
            'net_portfolio_value': 0,
            'total_yield': 0,
            'leverage_ratio': 0,
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'positions': []
        })

@app.route('/balances')
def get_balances():
    global bot
    
    if not bot:
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        testnet = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'
        
        if not api_key or not api_secret:
            return jsonify({'total_usd_value': 0, 'balances': {}, 'error': 'No API credentials'})
        
        bot = MultiAssetLeverageBot(api_key, api_secret, testnet)
    
    return jsonify(bot.get_account_balances())

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)