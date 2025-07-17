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
    earn_product_id: str = None
    loan_order_id: str = None

class BinanceAPI:
    """Complete Binance API for earn wallet leverage trading"""
    
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
                
                # Parse error response if it's JSON
                try:
                    error_data = response.json()
                    return {"error": f"HTTP {response.status_code}", "message": error_data.get('msg', error_msg), "code": error_data.get('code', response.status_code)}
                except:
                    return {"error": f"HTTP {response.status_code}", "message": error_msg}
                
        except requests.exceptions.Timeout:
            self.logger.error(f"❌ {endpoint} timeout")
            return {"error": "timeout", "message": "Request timed out"}
        except requests.exceptions.ConnectionError:
            self.logger.error(f"❌ {endpoint} connection error")
            return {"error": "connection", "message": "Connection failed"}
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
    
    # EARN WALLET APIs (Updated with working endpoints)
    def get_savings_products(self) -> List[Dict]:
        """Get available savings products (Simple Earn)"""
        return self._make_request("/sapi/v1/simple-earn/flexible/list", require_auth=True)
    
    def purchase_savings_product(self, product_id: str, amount: float) -> Dict:
        """Subscribe to flexible savings product"""
        params = {
            'productId': product_id,
            'amount': f"{amount:.8f}".rstrip('0').rstrip('.')
        }
        self.logger.info(f"💰 DEPOSITING TO EARN: {amount} - Product: {product_id}")
        return self._make_request("/sapi/v1/simple-earn/flexible/subscribe", params, method='POST', require_auth=True)
    
    def redeem_savings_product(self, product_id: str, amount: float) -> Dict:
        """Redeem from flexible savings"""
        params = {
            'productId': product_id,
            'amount': f"{amount:.8f}".rstrip('0').rstrip('.'),
            'type': 'FAST'
        }
        self.logger.info(f"💸 WITHDRAWING FROM EARN: {amount} - Product: {product_id}")
        return self._make_request("/sapi/v1/simple-earn/flexible/redeem", params, method='POST', require_auth=True)
    
    def get_savings_positions(self) -> List[Dict]:
        """Get flexible savings positions"""
        return self._make_request("/sapi/v1/simple-earn/flexible/position", require_auth=True)
    
    # CRYPTO LOAN APIs (Updated)
    def apply_crypto_loan(self, loan_coin: str, collateral_coin: str, loan_amount: float) -> Dict:
        """Apply for crypto loan"""
        params = {
            'loanCoin': loan_coin,
            'collateralCoin': collateral_coin,
            'loanAmount': f"{loan_amount:.2f}"
        }
        self.logger.info(f"🏦 APPLYING FOR CRYPTO LOAN: {loan_amount} {loan_coin} using {collateral_coin}")
        return self._make_request("/sapi/v1/loan/borrow", params, method='POST', require_auth=True)
    
    def repay_crypto_loan(self, order_id: str, amount: float) -> Dict:
        """Repay crypto loan"""
        params = {
            'orderId': order_id,
            'amount': f"{amount:.2f}"
        }
        self.logger.info(f"💳 REPAYING CRYPTO LOAN: {amount} - Order: {order_id}")
        return self._make_request("/sapi/v1/loan/repay", params, method='POST', require_auth=True)
    
    def get_loan_orders(self) -> List[Dict]:
        """Get crypto loan orders"""
        return self._make_request("/sapi/v1/loan/ongoing/orders", require_auth=True)

class EarnWalletLeverageBot:
    """EARN WALLET LEVERAGE BOT - Creates leveraged positions using Binance's lending products"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        
        # Enhanced logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Initialize API
        self.binance_api = BinanceAPI(api_key, api_secret, testnet)
        
        # Trading configuration - Only REAL Binance assets
        self.asset_config = self._initialize_asset_config()
        self.max_cascade_levels = 3
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
        self.savings_products_cache = {}
        
        # Load initial data
        self._update_price_cache()
        self._load_savings_products()
    
    def _initialize_asset_config(self) -> Dict[str, AssetConfig]:
        """Asset configuration - ONLY real Binance assets that exist on Earn"""
        return {
            # Major assets that definitely exist on Binance Earn
            'BTC': AssetConfig('BTC', 0.65, 0.04, 1, 0.025, 0.25),
            'ETH': AssetConfig('ETH', 0.60, 0.05, 1, 0.028, 0.30),
            'BNB': AssetConfig('BNB', 0.55, 0.06, 1, 0.030, 0.35),
            'USDT': AssetConfig('USDT', 0.70, 0.08, 1, 0.020, 0.10),
            'USDC': AssetConfig('USDC', 0.70, 0.075, 1, 0.021, 0.10),
            'ADA': AssetConfig('ADA', 0.50, 0.08, 2, 0.035, 0.50),
            'DOT': AssetConfig('DOT', 0.45, 0.09, 2, 0.038, 0.55),
            'LINK': AssetConfig('LINK', 0.40, 0.10, 2, 0.040, 0.60),
            'AVAX': AssetConfig('AVAX', 0.45, 0.09, 2, 0.037, 0.52),
            'MATIC': AssetConfig('MATIC', 0.40, 0.11, 2, 0.041, 0.58),
            'SOL': AssetConfig('SOL', 0.50, 0.08, 2, 0.036, 0.48),
        }
    
    def _update_price_cache(self):
        """Load current prices for our assets only"""
        try:
            all_prices = self.binance_api.get_all_prices()
            if all_prices and isinstance(all_prices, list):
                self.price_cache = {}
                
                # Only get prices for our configured assets
                for asset in self.asset_config.keys():
                    if asset == 'USDT':
                        self.price_cache['USDTUSDT'] = 1.0
                        continue
                    
                    symbol = f"{asset}USDT"
                    for price_data in all_prices:
                        if price_data.get('symbol') == symbol:
                            try:
                                self.price_cache[symbol] = float(price_data['price'])
                                break
                            except (ValueError, TypeError):
                                continue
                
                self.logger.info(f"📊 Price cache updated: {len(self.price_cache)} assets")
            else:
                self.logger.warning("Failed to get price data from API")
        except Exception as e:
            self.logger.error(f"Error updating price cache: {e}")
            self.price_cache = {}
    
    def _load_savings_products(self):
        """Load available savings products (Simple Earn)"""
        try:
            products = self.binance_api.get_savings_products()
            if products and isinstance(products, list):
                self.savings_products_cache = {}
                for product in products:
                    asset = product.get('asset', '')
                    status = product.get('status', '')
                    
                    # Only include products for our configured assets
                    if asset and status == 'PURCHASING' and asset in self.asset_config:
                        self.savings_products_cache[asset] = product
                
                self.logger.info(f"💰 Loaded {len(self.savings_products_cache)} savings products")
                
                # Log available assets
                available_assets = list(self.savings_products_cache.keys())
                if available_assets:
                    self.logger.info(f"📋 Available earn assets: {', '.join(available_assets)}")
                else:
                    self.logger.warning("⚠️ No savings products available for configured assets")
            else:
                self.logger.warning("Failed to load savings products from API")
                self.savings_products_cache = {}
        except Exception as e:
            self.logger.error(f"Error loading savings products: {e}")
            self.savings_products_cache = {}
    
    def _get_asset_price(self, asset: str) -> float:
        """Get current asset price"""
        if asset == 'USDT':
            return 1.0
        
        symbol = f"{asset}USDT"
        
        # Check cache first
        if symbol in self.price_cache:
            return self.price_cache[symbol]
        
        # Fallback API call
        try:
            price_data = self.binance_api.get_symbol_price(symbol)
            if "price" in price_data and "error" not in price_data:
                price = float(price_data['price'])
                self.price_cache[symbol] = price
                return price
        except Exception as e:
            self.logger.error(f"Error getting price for {symbol}: {e}")
        
        return 0.0
    
    def _get_symbol_info(self, symbol: str) -> Dict:
        """Get trading symbol information"""
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
                    return float(int(quantity / step_size) * step_size)
        return round(quantity, 6)
    
    async def start_trading(self, initial_capital: float):
        """Start EARN WALLET leverage trading"""
        try:
            self.logger.info(f"🚀 STARTING EARN WALLET LEVERAGE WITH ${initial_capital}")
            
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
            self.bot_status = "Executing Earn Strategy"
            
            # Execute earn wallet cascade strategy
            self.logger.info("🏦 EXECUTING EARN WALLET LEVERAGE STRATEGY")
            await self._execute_earn_cascade_strategy(initial_capital)
            
            self.bot_status = "Active Earn Positions"
            self.logger.info("✅ EARN WALLET LEVERAGE STRATEGY EXECUTED")
            
        except Exception as e:
            self.logger.error(f"❌ EARN TRADING FAILED: {e}")
            self.bot_status = "Error"
            raise
    
    async def _execute_earn_cascade_strategy(self, capital: float):
        """Execute earn wallet cascade leverage strategy"""
        try:
            current_capital = capital
            
            # Filter assets that have both price and savings product
            available_assets = []
            for asset_name, asset_config in self.asset_config.items():
                if asset_name == 'USDT':
                    continue
                    
                # Check if we have price data and savings product
                if (self._get_asset_price(asset_name) > 0 and 
                    asset_name in self.savings_products_cache):
                    available_assets.append((asset_name, asset_config))
            
            if not available_assets:
                raise Exception("No valid assets available for earn strategy")
            
            # Sort by safety (lower volatility first)
            available_assets.sort(key=lambda x: x[1].volatility_factor)
            
            self.logger.info(f"🎯 EXECUTING {min(self.max_cascade_levels, len(available_assets))} LEVEL CASCADE")
            self.logger.info(f"📋 Available assets: {', '.join([a[0] for a in available_assets])}")
            
            for level in range(min(self.max_cascade_levels, len(available_assets))):
                if current_capital < 20:
                    self.logger.warning(f"Capital too low: ${current_capital}")
                    break
                
                asset_name, asset_config = available_assets[level]
                
                # Conservative loan calculation
                max_loan = current_capital * asset_config.ltv_max * 0.85  # 15% safety buffer
                
                self.logger.info(f"🔄 LEVEL {level + 1}: {asset_name} with ${current_capital:.2f}")
                
                # Execute earn wallet level
                success = await self._execute_earn_level(
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
                await asyncio.sleep(3)
            
            self.logger.info(f"🎉 EARN CASCADE COMPLETE - Total leveraged: ${self.leveraged_capital:.2f}")
                    
        except Exception as e:
            self.logger.error(f"❌ EARN CASCADE FAILED: {e}")
            raise
    
    async def _execute_earn_level(self, level: int, asset: str, collateral_amount: float, 
                                 loan_amount: float) -> bool:
        """Execute one level of earn wallet leverage"""
        try:
            self.logger.info(f"🏦 EXECUTING EARN LEVEL {level}: {asset}")
            self.logger.info(f"💰 Collateral: ${collateral_amount:.2f} | Loan Target: ${loan_amount:.2f}")
            
            # 1. GET CURRENT PRICE
            asset_price = self._get_asset_price(asset)
            if asset_price <= 0:
                self.logger.error(f"❌ Invalid price for {asset}: {asset_price}")
                return False
            
            self.logger.info(f"💲 {asset} price: ${asset_price:.6f}")
            
            # 2. BUY ASSET ON SPOT
            symbol = f"{asset}USDT"
            raw_quantity = collateral_amount / asset_price
            quantity = self._format_quantity(symbol, raw_quantity)
            
            if quantity <= 0:
                self.logger.error(f"❌ Invalid quantity calculated: {quantity}")
                return False
            
            self.logger.info(f"🛒 Buying {quantity} {asset} for earn wallet")
            
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
            self.logger.info(f"✅ BOUGHT {quantity} {asset} - Order: {order_id}")
            
            # Wait for order execution
            await asyncio.sleep(2)
            
            # 3. DEPOSIT TO SAVINGS (EARN WALLET)
            savings_product = self.savings_products_cache[asset]
            product_id = savings_product.get('productId')
            
            if not product_id:
                self.logger.error(f"❌ No product ID for {asset}")
                return False
            
            self.logger.info(f"💰 Depositing {quantity} {asset} to savings...")
            
            deposit_result = self.binance_api.purchase_savings_product(product_id, quantity)
            
            if "error" in deposit_result:
                self.logger.error(f"❌ SAVINGS DEPOSIT FAILED: {deposit_result['message']}")
                return False
            
            self.logger.info(f"✅ DEPOSITED TO SAVINGS: {quantity} {asset}")
            
            # Wait for deposit to process
            await asyncio.sleep(3)
            
            # 4. APPLY FOR CRYPTO LOAN AGAINST SAVINGS POSITION
            self.logger.info(f"🏦 Applying for crypto loan: ${loan_amount:.2f} USDT using {asset}")
            
            loan_result = self.binance_api.apply_crypto_loan('USDT', asset, loan_amount)
            
            if "error" in loan_result:
                self.logger.error(f"❌ CRYPTO LOAN FAILED: {loan_result['message']}")
                # Try to withdraw from savings if loan fails
                try:
                    self.binance_api.redeem_savings_product(product_id, quantity)
                    self.logger.info(f"🔄 Withdrew {quantity} {asset} from savings after loan failure")
                except:
                    pass
                return False
            
            loan_order_id = loan_result.get('orderId', 'N/A')
            self.logger.info(f"✅ CRYPTO LOAN APPROVED: ${loan_amount:.2f} USDT - Order: {loan_order_id}")
            
            # 5. CREATE POSITION RECORD
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
                earn_product_id=product_id,
                loan_order_id=loan_order_id
            )
            
            self.positions.append(position)
            
            self.logger.info(f"🎯 EARN POSITION CREATED: Level {level} | {asset} | LTV: {current_ltv:.1%}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ EARN LEVEL {level} FAILED: {e}")
            return False
    
    def stop_trading(self):
        """Stop trading and close all earn positions"""
        try:
            self.logger.info("🛑 STOPPING EARN TRADING - CLOSING POSITIONS")
            self.is_running = False
            self.bot_status = "Closing Earn Positions"
            
            # Close all positions in reverse order
            for position in reversed(self.positions):
                self._close_earn_position(position)
            
            self.positions.clear()
            self.leveraged_capital = 0
            self.total_yield = 0
            self.bot_status = "Stopped"
            
            self.logger.info("✅ ALL EARN POSITIONS CLOSED")
            
        except Exception as e:
            self.logger.error(f"❌ EARN POSITION CLOSING ERROR: {e}")
            self.bot_status = "Error"
    
    def _close_earn_position(self, position: Position):
        """Close a single earn position"""
        try:
            self.logger.info(f"💥 CLOSING EARN POSITION: {position.asset} Level {position.level}")
            
            # 1. Repay crypto loan
            if position.loan_order_id:
                self.logger.info(f"💳 Repaying loan: {position.loan_order_id}")
                repay_result = self.binance_api.repay_crypto_loan(position.loan_order_id, position.loan_amount)
                
                if "error" not in repay_result:
                    self.logger.info(f"✅ LOAN REPAID: ${position.loan_amount:.2f}")
                else:
                    self.logger.error(f"❌ LOAN REPAY FAILED: {repay_result['message']}")
            
            # 2. Withdraw from savings
            if position.earn_product_id:
                time.sleep(2)  # Wait for repayment
                self.logger.info(f"💸 Withdrawing from savings: {position.collateral_amount} {position.asset}")
                
                withdraw_result = self.binance_api.redeem_savings_product(
                    position.earn_product_id, position.collateral_amount
                )
                
                if "error" not in withdraw_result:
                    self.logger.info(f"✅ WITHDRAWN FROM SAVINGS: {position.collateral_amount} {position.asset}")
                else:
                    self.logger.error(f"❌ WITHDRAW FAILED: {withdraw_result['message']}")
            
            # 3. Sell the asset
            time.sleep(2)  # Wait for withdrawal
            symbol = f"{position.asset}USDT"
            
            sell_order = self.binance_api.place_order(
                symbol=symbol,
                side='SELL',
                order_type='MARKET',
                quantity=position.collateral_amount
            )
            
            if "error" not in sell_order:
                self.logger.info(f"✅ SOLD {position.asset} - Order: {sell_order.get('orderId')}")
            else:
                self.logger.error(f"❌ SELL FAILED: {sell_order['message']}")
                
        except Exception as e:
            self.logger.error(f"❌ EARN POSITION CLOSE FAILED: {e}")
    
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
                    'order_id': pos.order_id,
                    'loan_order_id': pos.loan_order_id
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
            
            # Get spot balances
            for balance in account_info.get('balances', []):
                asset = balance['asset']
                free = float(balance['free'])
                locked = float(balance['locked'])
                total = free + locked
                
                if total > 0.001 and asset in self.asset_config:
                    price = self._get_asset_price(asset)
                    if price > 0:
                        usd_value = total * price
                        total_usd += usd_value
                        
                        balances[asset] = {
                            'spot_free': free,
                            'spot_locked': locked,
                            'spot_total': total,
                            'price': price,
                            'usd_value': usd_value,
                            'savings_amount': 0
                        }
            
            # Add savings positions
            try:
                savings_positions = self.binance_api.get_savings_positions()
                if savings_positions and isinstance(savings_positions, list):
                    for position in savings_positions:
                        asset = position.get('asset', '')
                        amount = float(position.get('totalAmount', 0))
                        
                        if asset and amount > 0.001 and asset in self.asset_config:
                            price = self._get_asset_price(asset)
                            if price > 0:
                                usd_value = amount * price
                                total_usd += usd_value
                                
                                if asset not in balances:
                                    balances[asset] = {
                                        'spot_free': 0, 'spot_locked': 0, 'spot_total': 0,
                                        'price': price, 'usd_value': 0, 'savings_amount': 0
                                    }
                                
                                balances[asset]['savings_amount'] = amount
                                balances[asset]['usd_value'] += usd_value
            except Exception as e:
                self.logger.error(f"Error getting savings positions: {e}")
            
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
    <title>Earn Wallet Leverage Bot - REAL LEVERAGED POSITIONS</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 0; background: #f5f5f5; }
        
        .earn-banner {
            background: linear-gradient(135deg, #28a745, #20c997);
            color: white;
            padding: 15px 20px;
            text-align: center;
            font-weight: bold;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.95; }
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
        .controls { background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px; border: 2px solid #28a745; }
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
        
        .earn-strategy {
            background: linear-gradient(135deg, #20c997, #17a2b8);
            color: white;
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 20px;
        }
        
        .strategy-steps {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        
        .strategy-step {
            background: rgba(255,255,255,0.1);
            padding: 15px;
            border-radius: 8px;
            text-align: center;
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
    <div class="earn-banner">
        🏦 BINANCE SIMPLE EARN LEVERAGE - REAL LEVERAGED POSITIONS
    </div>

    <div class="container">
        <div class="header">
            <h1>🏦 Simple Earn Leverage Bot</h1>
            <p><strong>Creates Leveraged Positions Using Binance Simple Earn</strong></p>
        </div>
        
        <div class="earn-strategy">
            <h3>🎯 Simple Earn Leverage Strategy</h3>
            <p>This bot creates leveraged positions by depositing assets into Binance Simple Earn and borrowing against them:</p>
            <div class="strategy-steps">
                <div class="strategy-step">
                    <strong>1. Buy Asset</strong><br>
                    <small>Purchase crypto on spot market</small>
                </div>
                <div class="strategy-step">
                    <strong>2. Deposit to Simple Earn</strong><br>
                    <small>Move to flexible savings</small>
                </div>
                <div class="strategy-step">
                    <strong>3. Borrow Against</strong><br>
                    <small>Take crypto loan using savings position</small>
                </div>
                <div class="strategy-step">
                    <strong>4. Cascade Repeat</strong><br>
                    <small>Use borrowed funds for next level</small>
                </div>
            </div>
        </div>
        
        <div class="balances-section">
            <h3>💼 Account Overview</h3>
            <div class="balance-grid">
                <div class="balance-item">
                    <div class="balance-label">Available USDT</div>
                    <div class="balance-value">$<span id="available-usdt">0.00</span></div>
                </div>
                <div class="balance-item">
                    <div class="balance-label">Earn Positions</div>
                    <div class="balance-value"><span id="position-count">0</span></div>
                </div>
                <div class="balance-item">
                    <div class="balance-label">Total Loans</div>
                    <div class="balance-value">$<span id="total-loans">0.00</span></div>
                </div>
                <div class="balance-item">
                    <div class="balance-label">Net Value</div>
                    <div class="balance-value">$<span id="net-portfolio">0.00</span></div>
                </div>
            </div>
        </div>
        
        <div class="controls">
            <h3>🏦 Simple Earn Leverage Control</h3>
            <div class="input-group">
                <label for="capital">Capital to Deploy (USD):</label>
                <input type="number" id="capital" value="50" min="20" step="10">
            </div>
            <button class="btn btn-success" onclick="startEarnLeverage()">🏦 START EARN LEVERAGE</button>
            <button class="btn btn-danger" onclick="stopTrading()">🛑 CLOSE ALL POSITIONS</button>
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
            <h3>📊 Simple Earn Leverage Positions</h3>
            <table class="positions-table" id="positions-table">
                <thead>
                    <tr>
                        <th>Level</th>
                        <th>Asset</th>
                        <th>Savings Amount</th>
                        <th>Loan (USDT)</th>
                        <th>LTV</th>
                        <th>USD Value</th>
                        <th>Loan Order</th>
                    </tr>
                </thead>
                <tbody id="positions-body">
                    <tr>
                        <td colspan="7" style="text-align: center; color: #666;">No earn positions</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <script>
        let isTrading = false;
        
        async function startEarnLeverage() {
            if (isTrading) return;
            
            const capital = document.getElementById('capital').value;
            isTrading = true;
            
            try {
                const response = await fetch('/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ capital: parseFloat(capital) })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    alert('✅ EARN LEVERAGE STARTED! Creating leveraged positions...');
                    setTimeout(updateStatus, 2000);
                } else {
                    alert(`❌ Failed: ${result.error}`);
                }
            } catch (error) {
                alert(`❌ Error: ${error.message}`);
            } finally {
                isTrading = false;
            }
        }
        
        async function stopTrading() {
            try {
                const response = await fetch('/stop', { method: 'POST' });
                const result = await response.json();
                alert('🛑 Earn positions closed');
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
                
                // Update balances
                const usdtBalance = balanceData.balances['USDT'];
                if (usdtBalance) {
                    document.getElementById('available-usdt').textContent = usdtBalance.spot_free.toLocaleString(undefined, {minimumFractionDigits: 2});
                }
                
                document.getElementById('total-loans').textContent = statusData.leveraged_capital.toLocaleString();
                document.getElementById('net-portfolio').textContent = statusData.net_portfolio_value.toLocaleString();
                
                // Update positions table
                const tbody = document.getElementById('positions-body');
                tbody.innerHTML = '';
                
                if (statusData.positions.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #666;">No earn positions</td></tr>';
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
                            <td><code>${pos.loan_order_id || 'N/A'}</code></td>
                        `;
                        tbody.appendChild(row);
                    });
                }
            } catch (error) {
                console.error('Error updating status:', error);
            }
        }
        
        // Auto-refresh every 15 seconds
        setInterval(updateStatus, 15000);
        
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
        bot = EarnWalletLeverageBot(api_key, api_secret, testnet)
        
        # Start earn leverage in background
        def start_async():
            asyncio.run(bot.start_trading(capital))
        
        thread = threading.Thread(target=start_async)
        thread.start()
        
        return jsonify({'success': True, 'message': 'Simple Earn leverage executing'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/stop', methods=['POST'])
def stop_trading():
    global bot
    try:
        if bot:
            bot.stop_trading()
        return jsonify({'success': True, 'message': 'Earn positions closed'})
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
        
        bot = EarnWalletLeverageBot(api_key, api_secret, testnet)
    
    return jsonify(bot.get_account_balances())

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)