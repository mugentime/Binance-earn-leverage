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

class BinanceAPI:
    """Complete Binance API integration for real trading"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://testnet.binance.vision" if testnet else "https://api.binance.com"
        self.headers = {'X-MBX-APIKEY': api_key}
        
    def _generate_signature(self, query_string: str) -> str:
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _make_request(self, endpoint: str, params: Dict = None, method: str = 'GET') -> Dict:
        if params is None:
            params = {}
        
        params['timestamp'] = int(time.time() * 1000)
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        params['signature'] = self._generate_signature(query_string)
        
        try:
            if method == 'GET':
                response = requests.get(f"{self.base_url}{endpoint}", params=params, headers=self.headers)
            elif method == 'POST':
                response = requests.post(f"{self.base_url}{endpoint}", params=params, headers=self.headers)
            elif method == 'DELETE':
                response = requests.delete(f"{self.base_url}{endpoint}", params=params, headers=self.headers)
            
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logging.error(f"API request failed: {e}")
            if hasattr(e, 'response') and e.response:
                logging.error(f"Response: {e.response.text}")
            return {}
    
    def get_account_info(self) -> Dict:
        return self._make_request("/api/v3/account")
    
    def get_symbol_price(self, symbol: str) -> Dict:
        return self._make_request("/api/v3/ticker/price", {"symbol": symbol})
    
    def get_all_prices(self) -> List[Dict]:
        return self._make_request("/api/v3/ticker/price")
    
    def get_exchange_info(self) -> Dict:
        return self._make_request("/api/v3/exchangeInfo")
    
    def place_order(self, symbol: str, side: str, order_type: str, quantity: float, 
                   price: float = None, **kwargs) -> Dict:
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': quantity
        }
        if price:
            params['price'] = price
        params.update(kwargs)
        return self._make_request("/api/v3/order", params, method='POST')
    
    def get_order_status(self, symbol: str, order_id: str) -> Dict:
        return self._make_request("/api/v3/order", {
            'symbol': symbol,
            'orderId': order_id
        })
    
    def cancel_order(self, symbol: str, order_id: str) -> Dict:
        return self._make_request("/api/v3/order", {
            'symbol': symbol,
            'orderId': order_id
        }, method='DELETE')
    
    # Margin Trading
    def get_margin_account(self) -> Dict:
        return self._make_request("/sapi/v1/margin/account")
    
    def margin_borrow(self, asset: str, amount: float) -> Dict:
        return self._make_request("/sapi/v1/margin/loan", {
            'asset': asset,
            'amount': amount
        }, method='POST')
    
    def margin_repay(self, asset: str, amount: float) -> Dict:
        return self._make_request("/sapi/v1/margin/repay", {
            'asset': asset,
            'amount': amount
        }, method='POST')
    
    def transfer_to_margin(self, asset: str, amount: float) -> Dict:
        return self._make_request("/sapi/v1/margin/transfer", {
            'asset': asset,
            'amount': amount,
            'type': 1  # MAIN_MARGIN
        }, method='POST')
    
    def transfer_from_margin(self, asset: str, amount: float) -> Dict:
        return self._make_request("/sapi/v1/margin/transfer", {
            'asset': asset,
            'amount': amount,
            'type': 2  # MARGIN_MAIN
        }, method='POST')
    
    # Savings/Earn
    def get_flexible_products(self) -> List[Dict]:
        return self._make_request("/sapi/v1/lending/daily/product/list", {
            'status': 'PURCHASING'
        })
    
    def purchase_flexible_product(self, product_id: str, amount: float) -> Dict:
        return self._make_request("/sapi/v1/lending/daily/purchase", {
            'productId': product_id,
            'amount': amount
        }, method='POST')
    
    def redeem_flexible_product(self, product_id: str, amount: float) -> Dict:
        return self._make_request("/sapi/v1/lending/daily/redeem", {
            'productId': product_id,
            'amount': amount,
            'type': 'FAST'
        }, method='POST')
    
    def get_flexible_positions(self) -> List[Dict]:
        return self._make_request("/sapi/v1/lending/daily/token/position")

class MultiAssetLeverageBot:
    """Real Multi-Asset Leverage Bot with Binance Integration"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        
        # Initialize Binance API
        self.binance_api = BinanceAPI(api_key, api_secret, testnet)
        
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
        
        # Market data cache
        self.price_cache = {}
        self.flexible_products_cache = {}
        self.account_cache = {}
        self.last_cache_update = datetime.now() - timedelta(hours=1)
        
        # Real-time monitoring
        self._start_monitoring_thread()
    
    def _initialize_asset_config(self) -> Dict[str, AssetConfig]:
        """Initialize asset configuration with real market data"""
        base_config = {
            # Tier 1 - Blue Chip Assets
            'BTC': AssetConfig('BTC', 0.75, 0.04, 1, 0.022, 0.25),
            'ETH': AssetConfig('ETH', 0.70, 0.05, 1, 0.025, 0.30),
            'BNB': AssetConfig('BNB', 0.65, 0.07, 1, 0.028, 0.35),
            'USDT': AssetConfig('USDT', 0.85, 0.08, 1, 0.020, 0.10),
            'USDC': AssetConfig('USDC', 0.85, 0.075, 1, 0.021, 0.10),
            
            # Tier 2 - Established DeFi
            'CVX': AssetConfig('CVX', 0.55, 0.12, 2, 0.035, 0.50),
            'ZRX': AssetConfig('ZRX', 0.50, 0.14, 2, 0.038, 0.55),
            'ETHFI': AssetConfig('ETHFI', 0.45, 0.16, 2, 0.040, 0.60),
            'HIFI': AssetConfig('HIFI', 0.40, 0.18, 2, 0.042, 0.65),
            
            # Tier 3 - Mid-Cap
            'ONT': AssetConfig('ONT', 0.45, 0.15, 3, 0.039, 0.58),
            'LIT': AssetConfig('LIT', 0.42, 0.17, 3, 0.041, 0.62),
            'LSK': AssetConfig('LSK', 0.40, 0.19, 3, 0.043, 0.65),
            'SKL': AssetConfig('SKL', 0.38, 0.21, 3, 0.045, 0.68),
            'GLMR': AssetConfig('GLMR', 0.35, 0.22, 3, 0.046, 0.70),
            'RIF': AssetConfig('RIF', 0.33, 0.24, 3, 0.048, 0.72),
            'FLM': AssetConfig('FLM', 0.30, 0.26, 3, 0.050, 0.75),
            'STPT': AssetConfig('STPT', 0.32, 0.25, 3, 0.049, 0.73),
            'DUSK': AssetConfig('DUSK', 0.35, 0.23, 3, 0.047, 0.69),
            
            # Tier 4 - High Risk/Reward
            'BNX': AssetConfig('BNX', 0.30, 0.28, 4, 0.052, 0.80),
            'BOME': AssetConfig('BOME', 0.25, 0.32, 4, 0.058, 0.90),
            'OXT': AssetConfig('OXT', 0.28, 0.30, 4, 0.055, 0.85),
            'RONIN': AssetConfig('RONIN', 0.35, 0.27, 4, 0.051, 0.78),
            'WIF': AssetConfig('WIF', 0.22, 0.35, 4, 0.062, 0.95),
            'XVG': AssetConfig('XVG', 0.25, 0.33, 4, 0.060, 0.88),
        }
        
        # Update with real rates from Binance
        self._update_rates_from_binance(base_config)
        return base_config
    
    def _update_rates_from_binance(self, config: Dict[str, AssetConfig]):
        """Update asset configuration with real Binance rates"""
        try:
            # Get flexible products for earn rates
            flexible_products = self.binance_api.get_flexible_products()
            
            if flexible_products:
                for product in flexible_products:
                    asset = product.get('asset', '')
                    if asset in config:
                        yield_rate = float(product.get('avgAnnualInterestRate', 0)) / 100
                        if yield_rate > 0:
                            config[asset].yield_rate = yield_rate
                        
                        # Cache product for later use
                        self.flexible_products_cache[asset] = product
            
            # Get margin account info for borrowing rates
            margin_account = self.binance_api.get_margin_account()
            
            if margin_account and 'userAssets' in margin_account:
                for asset_info in margin_account['userAssets']:
                    asset = asset_info.get('asset', '')
                    if asset in config:
                        # Update based on current margin rates (simplified calculation)
                        borrowed = float(asset_info.get('borrowed', 0))
                        interest = float(asset_info.get('interest', 0))
                        if borrowed > 0 and interest > 0:
                            daily_rate = interest / borrowed
                            annual_rate = daily_rate * 365
                            config[asset].loan_rate = min(annual_rate, 0.5)  # Cap at 50%
                            
        except Exception as e:
            self.logger.error(f"Error updating rates from Binance: {e}")
    
    def _start_monitoring_thread(self):
        """Start background monitoring thread"""
        def monitor():
            while True:
                try:
                    if self.is_running:
                        self._update_cache()
                        self._monitor_positions()
                        self._check_rebalance_needed()
                    time.sleep(30)  # Check every 30 seconds
                except Exception as e:
                    self.logger.error(f"Error in monitoring thread: {e}")
                    time.sleep(60)
        
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
    
    def _update_cache(self):
        """Update market data cache"""
        try:
            # Update prices
            all_prices = self.binance_api.get_all_prices()
            if all_prices:
                self.price_cache = {p['symbol']: float(p['price']) for p in all_prices}
            
            # Update account info
            account_info = self.binance_api.get_account_info()
            if account_info:
                self.account_cache = account_info
            
            self.last_cache_update = datetime.now()
            
        except Exception as e:
            self.logger.error(f"Error updating cache: {e}")
    
    def _monitor_positions(self):
        """Monitor active positions for risk management"""
        try:
            for position in self.positions:
                # Get current prices
                collateral_price = self._get_asset_price(position.asset)
                loan_asset_price = self._get_asset_price(position.loan_asset)
                
                if collateral_price > 0 and loan_asset_price > 0:
                    # Calculate current LTV
                    collateral_value = position.collateral_amount * collateral_price
                    loan_value = position.loan_amount * loan_asset_price
                    current_ltv = loan_value / collateral_value
                    
                    position.current_ltv = current_ltv
                    
                    # Risk management
                    asset_config = self.asset_config[position.asset]
                    
                    if current_ltv > asset_config.ltv_max * 0.9:  # 90% of max LTV
                        self.logger.warning(f"High LTV warning for {position.asset}: {current_ltv:.2%}")
                        
                    if current_ltv > self.emergency_ltv:
                        self.logger.error(f"Emergency LTV breach for {position.asset}: {current_ltv:.2%}")
                        self._emergency_liquidate_position(position)
                        
        except Exception as e:
            self.logger.error(f"Error monitoring positions: {e}")
    
    def _get_asset_price(self, asset: str) -> float:
        """Get current asset price in USDT"""
        try:
            if asset == 'USDT':
                return 1.0
                
            symbol = f"{asset}USDT"
            if symbol in self.price_cache:
                return self.price_cache[symbol]
            
            # Fallback to API call
            price_data = self.binance_api.get_symbol_price(symbol)
            if price_data and 'price' in price_data:
                return float(price_data['price'])
                
        except Exception as e:
            self.logger.error(f"Error getting price for {asset}: {e}")
        
        return 0.0
    
    def _emergency_liquidate_position(self, position: Position):
        """Emergency liquidation of position"""
        try:
            self.logger.info(f"Starting emergency liquidation for {position.asset}")
            
            # 1. Redeem from flexible savings
            if position.asset in self.flexible_products_cache:
                product = self.flexible_products_cache[position.asset]
                product_id = product.get('productId')
                if product_id:
                    self.binance_api.redeem_flexible_product(product_id, position.collateral_amount)
                    self.logger.info(f"Redeemed {position.collateral_amount} {position.asset}")
            
            # 2. Sell collateral
            symbol = f"{position.asset}USDT"
            sell_order = self.binance_api.place_order(
                symbol=symbol,
                side='SELL',
                order_type='MARKET',
                quantity=position.collateral_amount
            )
            
            if sell_order and 'orderId' in sell_order:
                self.logger.info(f"Placed sell order for {position.asset}: {sell_order['orderId']}")
                
                # 3. Repay loan
                time.sleep(2)  # Wait for order to execute
                self.binance_api.margin_repay(position.loan_asset, position.loan_amount)
                self.logger.info(f"Repaid {position.loan_amount} {position.loan_asset}")
            
            # Remove position
            self.positions.remove(position)
            
        except Exception as e:
            self.logger.error(f"Error in emergency liquidation: {e}")
    
    def _check_rebalance_needed(self):
        """Check if portfolio rebalancing is needed"""
        if datetime.now() - self.last_rebalance < timedelta(hours=1):
            return
        
        try:
            # Simple rebalancing logic
            total_value = sum(pos.collateral_amount * self._get_asset_price(pos.asset) for pos in self.positions)
            if total_value == 0:
                return
            
            # Check if any position is too large (>40% of portfolio)
            for position in self.positions:
                position_value = position.collateral_amount * self._get_asset_price(position.asset)
                position_weight = position_value / total_value
                
                if position_weight > 0.4:
                    self.logger.info(f"Rebalancing needed for {position.asset} ({position_weight:.1%})")
                    # Implement rebalancing logic here
                    
            self.last_rebalance = datetime.now()
            
        except Exception as e:
            self.logger.error(f"Error checking rebalance: {e}")
    
    async def start_trading(self, initial_capital: float):
        """Start real trading operations"""
        try:
            self.logger.info(f"Starting real trading with capital: ${initial_capital}")
            self.total_capital = initial_capital
            self.is_running = True
            self.bot_status = "Running"
            
            # Verify account and balances
            account_info = self.binance_api.get_account_info()
            if not account_info:
                raise Exception("Failed to get account info")
            
            # Get USDT balance
            usdt_balance = 0
            for balance in account_info.get('balances', []):
                if balance['asset'] == 'USDT':
                    usdt_balance = float(balance['free'])
                    break
            
            if usdt_balance < initial_capital:
                raise Exception(f"Insufficient USDT balance. Available: {usdt_balance}, Required: {initial_capital}")
            
            # Execute cascade strategy
            await self._execute_cascade_strategy(initial_capital)
            
            self.logger.info("Trading started successfully")
            
        except Exception as e:
            self.logger.error(f"Trading error: {e}")
            self.bot_status = "Error"
            raise
    
    async def _execute_cascade_strategy(self, capital: float):
        """Execute the cascade leverage strategy"""
        try:
            current_capital = capital
            
            # Sort assets by profit potential
            sorted_assets = sorted(
                [(k, v) for k, v in self.asset_config.items() if k not in ['USDT', 'USDC']],
                key=lambda x: (x[1].yield_rate - x[1].loan_rate) / (1 + x[1].volatility_factor),
                reverse=True
            )
            
            for level in range(min(self.max_cascade_levels, len(sorted_assets))):
                if current_capital < 50:  # Minimum $50 USD
                    break
                
                asset_name, asset_config = sorted_assets[level]
                
                # Calculate loan amount
                max_loan = current_capital * asset_config.ltv_max * 0.95  # 5% buffer
                
                # Execute the cascade level
                success = await self._execute_cascade_level(
                    level + 1, asset_name, current_capital, max_loan
                )
                
                if success:
                    current_capital = max_loan
                else:
                    self.logger.warning(f"Failed to execute level {level + 1}, stopping cascade")
                    break
                    
        except Exception as e:
            self.logger.error(f"Error executing cascade strategy: {e}")
            raise
    
    async def _execute_cascade_level(self, level: int, asset: str, collateral_amount: float, 
                                   loan_amount: float) -> bool:
        """Execute a single cascade level"""
        try:
            self.logger.info(f"Executing level {level}: {asset}, Collateral: ${collateral_amount:.2f}, Loan: ${loan_amount:.2f}")
            
            # 1. Buy the asset
            symbol = f"{asset}USDT"
            asset_price = self._get_asset_price(asset)
            
            if asset_price <= 0:
                self.logger.error(f"Invalid price for {asset}")
                return False
            
            quantity = collateral_amount / asset_price
            
            buy_order = self.binance_api.place_order(
                symbol=symbol,
                side='BUY',
                order_type='MARKET',
                quantity=quantity
            )
            
            if not buy_order or 'orderId' not in buy_order:
                self.logger.error(f"Failed to place buy order for {asset}")
                return False
            
            self.logger.info(f"Bought {quantity:.6f} {asset} - Order ID: {buy_order['orderId']}")
            
            # 2. Transfer to margin account
            transfer_result = self.binance_api.transfer_to_margin(asset, quantity)
            if not transfer_result:
                self.logger.error(f"Failed to transfer {asset} to margin")
                return False
            
            # 3. Borrow USDT against the asset
            borrow_result = self.binance_api.margin_borrow('USDT', loan_amount)
            if not borrow_result:
                self.logger.error(f"Failed to borrow USDT against {asset}")
                return False
            
            self.logger.info(f"Borrowed ${loan_amount:.2f} USDT against {asset}")
            
            # 4. Transfer borrowed USDT back to spot for next level
            transfer_back = self.binance_api.transfer_from_margin('USDT', loan_amount)
            if not transfer_back:
                self.logger.error(f"Failed to transfer borrowed USDT to spot")
                return False
            
            # 5. Optionally put in flexible savings for additional yield
            if asset in self.flexible_products_cache:
                product = self.flexible_products_cache[asset]
                product_id = product.get('productId')
                if product_id:
                    self.binance_api.purchase_flexible_product(product_id, quantity)
                    self.logger.info(f"Put {quantity:.6f} {asset} in flexible savings")
            
            # 6. Create position record
            position = Position(
                asset=asset,
                collateral_amount=quantity,
                loan_amount=loan_amount,
                loan_asset='USDT',
                current_ltv=loan_amount / collateral_amount / asset_price,
                yield_earned=0,
                level=level,
                order_id=buy_order['orderId']
            )
            
            self.positions.append(position)
            self.leveraged_capital += loan_amount
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error executing cascade level {level}: {e}")
            return False
    
    def stop_trading(self):
        """Stop trading and liquidate all positions"""
        try:
            self.logger.info("Stopping trading and liquidating positions")
            self.is_running = False
            self.bot_status = "Stopping"
            
            # Liquidate all positions
            for position in self.positions[:]:  # Copy list to avoid modification during iteration
                self._emergency_liquidate_position(position)
            
            self.positions.clear()
            self.leveraged_capital = 0
            self.total_yield = 0
            self.bot_status = "Stopped"
            
            self.logger.info("All positions liquidated, trading stopped")
            
        except Exception as e:
            self.logger.error(f"Error stopping trading: {e}")
            self.bot_status = "Error"
    
    def get_portfolio_status(self) -> Dict:
        """Get current portfolio status"""
        total_collateral_value = 0
        total_loan_value = 0
        
        for position in self.positions:
            asset_price = self._get_asset_price(position.asset)
            loan_price = self._get_asset_price(position.loan_asset)
            
            total_collateral_value += position.collateral_amount * asset_price
            total_loan_value += position.loan_amount * loan_price
        
        net_value = total_collateral_value - total_loan_value
        leverage_ratio = total_loan_value / self.total_capital if self.total_capital > 0 else 0
        
        # Calculate estimated annual yield
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
        """Get current account balances"""
        try:
            account_info = self.binance_api.get_account_info()
            margin_account = self.binance_api.get_margin_account()
            flexible_positions = self.binance_api.get_flexible_positions()
            
            balances = {}
            total_usd = 0
            
            # Spot balances
            if account_info and 'balances' in account_info:
                for balance in account_info['balances']:
                    asset = balance['asset']
                    free = float(balance['free'])
                    locked = float(balance['locked'])
                    total = free + locked
                    
                    if total > 0.001:  # Filter dust
                        price = self._get_asset_price(asset)
                        usd_value = total * price
                        total_usd += usd_value
                        
                        balances[asset] = {
                            'spot_free': free,
                            'spot_locked': locked,
                            'spot_total': total,
                            'margin_net': 0,
                            'margin_borrowed': 0,
                            'earn_amount': 0,
                            'price': price,
                            'usd_value': usd_value
                        }
            
            # Margin balances
            if margin_account and 'userAssets' in margin_account:
                for asset_info in margin_account['userAssets']:
                    asset = asset_info['asset']
                    net_asset = float(asset_info.get('netAsset', 0))
                    borrowed = float(asset_info.get('borrowed', 0))
                    
                    if asset not in balances:
                        balances[asset] = {
                            'spot_free': 0, 'spot_locked': 0, 'spot_total': 0,
                            'margin_net': 0, 'margin_borrowed': 0, 'earn_amount': 0,
                            'price': self._get_asset_price(asset), 'usd_value': 0
                        }
                    
                    balances[asset]['margin_net'] = net_asset
                    balances[asset]['margin_borrowed'] = borrowed
                    
                    price = self._get_asset_price(asset)
                    margin_usd_value = net_asset * price
                    balances[asset]['usd_value'] += margin_usd_value
                    total_usd += margin_usd_value
            
            # Flexible savings positions
            if flexible_positions:
                for position in flexible_positions:
                    asset = position.get('asset', '')
                    amount = float(position.get('totalAmount', 0))
                    
                    if asset and amount > 0.001:
                        if asset not in balances:
                            balances[asset] = {
                                'spot_free': 0, 'spot_locked': 0, 'spot_total': 0,
                                'margin_net': 0, 'margin_borrowed': 0, 'earn_amount': 0,
                                'price': self._get_asset_price(asset), 'usd_value': 0
                            }
                        
                        balances[asset]['earn_amount'] = amount
                        
                        price = self._get_asset_price(asset)
                        earn_usd_value = amount * price
                        balances[asset]['usd_value'] += earn_usd_value
                        total_usd += earn_usd_value
            
            return {
                'total_usd_value': total_usd,
                'balances': balances,
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
        except Exception as e:
            self.logger.error(f"Error getting account balances: {e}")
            return {'total_usd_value': 0, 'balances': {}, 'error': str(e)}

# Global bot instance
bot = None

# Flask Application
app = Flask(__name__)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Multi-Asset Leverage Bot - LIVE TRADING</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 0; background: #f5f5f5; }
        
        .live-banner {
            background: linear-gradient(135deg, #ff4757, #ff6b7a);
            color: white;
            padding: 10px 20px;
            text-align: center;
            font-weight: bold;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.8; }
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
        .status-stopping { background: #ffc107; color: #333; }
        .status-error { background: #dc3545; }
        
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
        
        .asset-balances {
            max-height: 400px;
            overflow-y: auto;
            background: rgba(255,255,255,0.1);
            border-radius: 8px;
            padding: 15px;
        }
        
        .warning { background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 8px; margin: 10px 0; }
        .success { background: #d4edda; border: 1px solid #c3e6cb; padding: 15px; border-radius: 8px; margin: 10px 0; }
        .error { background: #f8d7da; border: 1px solid #f5c6cb; padding: 15px; border-radius: 8px; margin: 10px 0; }
        
        @media (max-width: 768px) {
            .status { flex-direction: column; }
            .metric { margin: 5px 0; }
        }
    </style>
</head>
<body>
    <div class="live-banner">
        🔴 LIVE TRADING MODE - REAL MONEY - USE WITH EXTREME CAUTION
    </div>

    <div class="container">
        <div class="header">
            <h1>🚀 Multi-Asset Leverage Bot</h1>
            <p><strong>LIVE TRADING</strong> - Advanced Cascade Leverage Strategy</p>
        </div>
        
        <div class="balances-section">
            <h3>💼 Account Overview</h3>
            <div class="balance-grid">
                <div class="balance-item">
                    <div class="balance-label">Total Portfolio Value</div>
                    <div class="balance-value">$<span id="total-portfolio">0.00</span></div>
                </div>
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
            </div>
            
            <details>
                <summary style="cursor: pointer; padding: 10px; background: rgba(255,255,255,0.1); border-radius: 5px;">
                    📊 View All Asset Balances
                </summary>
                <div class="asset-balances" id="asset-balances">
                    Loading balances...
                </div>
            </details>
        </div>
        
        <div class="controls">
            <h3>🎯 Live Trading Control</h3>
            <div class="warning">
                <strong>⚠️ Warning:</strong> This will execute real trades with real money. Ensure you understand the risks.
            </div>
            <div class="input-group">
                <label for="capital">Capital to Deploy (USD):</label>
                <input type="number" id="capital" value="1000" min="50" step="50">
            </div>
            <button class="btn btn-success" onclick="startTrading()">🚀 START LIVE TRADING</button>
            <button class="btn btn-danger" onclick="stopTrading()">⛔ STOP & LIQUIDATE ALL</button>
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
                <div>Total Loans</div>
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
            <h3>📊 Active Trading Positions</h3>
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
        
        async function startTrading() {
            if (isTrading) return;
            
            const capital = document.getElementById('capital').value;
            
            if (!confirm(`Are you sure you want to start live trading with $${capital}? This will use real money and execute real trades.`)) {
                return;
            }
            
            if (!confirm('FINAL WARNING: This is live trading with real money. Losses can occur. Continue?')) {
                return;
            }
            
            isTrading = true;
            
            try {
                showMessage('Starting live trading...', 'warning');
                
                const response = await fetch('/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ capital: parseFloat(capital) })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    showMessage('Live trading started successfully!', 'success');
                    setTimeout(updateStatus, 2000);
                } else {
                    showMessage(`Error: ${result.error}`, 'error');
                }
            } catch (error) {
                showMessage(`Network error: ${error.message}`, 'error');
            } finally {
                isTrading = false;
            }
        }
        
        async function stopTrading() {
            if (!confirm('Stop trading and liquidate ALL positions? This will close all open trades.')) {
                return;
            }
            
            try {
                showMessage('Stopping trading and liquidating positions...', 'warning');
                
                const response = await fetch('/stop', { method: 'POST' });
                const result = await response.json();
                
                if (result.success) {
                    showMessage('Trading stopped and positions liquidated.', 'success');
                    setTimeout(updateStatus, 2000);
                } else {
                    showMessage(`Error: ${result.error}`, 'error');
                }
            } catch (error) {
                showMessage(`Network error: ${error.message}`, 'error');
            }
        }
        
        async function updateStatus() {
            try {
                const response = await fetch('/status');
                const data = await response.json();
                
                // Update metrics
                document.getElementById('total-capital').textContent = data.total_capital.toLocaleString();
                document.getElementById('leveraged-capital').textContent = data.leveraged_capital.toLocaleString();
                document.getElementById('net-value').textContent = data.net_portfolio_value.toLocaleString();
                document.getElementById('total-yield').textContent = data.total_yield.toFixed(2);
                document.getElementById('position-count').textContent = data.total_positions;
                
                // Update bot status
                const statusElement = document.getElementById('bot-status');
                statusElement.textContent = data.bot_status;
                statusElement.className = 'status-indicator status-' + data.bot_status.toLowerCase();
                
                // Update positions table
                const tbody = document.getElementById('positions-body');
                tbody.innerHTML = '';
                
                if (data.positions.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #666;">No active positions</td></tr>';
                } else {
                    data.positions.forEach(pos => {
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>${pos.level}</td>
                            <td><strong>${pos.asset}</strong></td>
                            <td>${pos.collateral.toFixed(6)}</td>
                            <td>$${pos.loan.toLocaleString()}</td>
                            <td>${(pos.ltv * 100).toFixed(1)}%</td>
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
        
        async function updateBalances() {
            try {
                const response = await fetch('/balances');
                const data = await response.json();
                
                // Update main balance metrics
                document.getElementById('total-portfolio').textContent = data.total_usd_value.toLocaleString(undefined, {minimumFractionDigits: 2});
                
                // Find USDT balance
                const usdtBalance = data.balances['USDT'];
                if (usdtBalance) {
                    document.getElementById('available-usdt').textContent = usdtBalance.spot_free.toLocaleString(undefined, {minimumFractionDigits: 2});
                }
                
                // Calculate total loans
                let totalLoans = 0;
                Object.values(data.balances).forEach(balance => {
                    totalLoans += balance.margin_borrowed * balance.price;
                });
                document.getElementById('total-loans').textContent = totalLoans.toLocaleString(undefined, {minimumFractionDigits: 2});
                
                // Update detailed balances
                const balancesDiv = document.getElementById('asset-balances');
                balancesDiv.innerHTML = '';
                
                Object.entries(data.balances).forEach(([asset, balance]) => {
                    if (balance.usd_value > 1) { // Only show balances > $1
                        const div = document.createElement('div');
                        div.style.cssText = 'margin: 5px 0; padding: 10px; background: rgba(255,255,255,0.1); border-radius: 5px;';
                        div.innerHTML = `
                            <strong>${asset}</strong> - $${balance.usd_value.toFixed(2)}
                            <br><small>
                                Spot: ${balance.spot_total.toFixed(6)} | 
                                Margin: ${balance.margin_net.toFixed(6)} | 
                                Borrowed: ${balance.margin_borrowed.toFixed(6)} |
                                Earn: ${balance.earn_amount.toFixed(6)}
                            </small>
                        `;
                        balancesDiv.appendChild(div);
                    }
                });
                
            } catch (error) {
                console.error('Error updating balances:', error);
            }
        }
        
        function showMessage(text, type) {
            // Remove existing messages
            const existing = document.querySelector('.message');
            if (existing) existing.remove();
            
            const div = document.createElement('div');
            div.className = `message ${type}`;
            div.textContent = text;
            
            const controls = document.querySelector('.controls');
            controls.appendChild(div);
            
            setTimeout(() => div.remove(), 5000);
        }
        
        // Auto-update intervals
        setInterval(updateStatus, 15000);   // Every 15 seconds
        setInterval(updateBalances, 30000); // Every 30 seconds
        
        // Initial load
        updateStatus();
        updateBalances();
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
        capital = data.get('capital', 1000)
        
        # Get API credentials from environment
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        testnet = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'
        
        if not api_key or not api_secret:
            return jsonify({'success': False, 'error': 'API credentials not configured. Set BINANCE_API_KEY and BINANCE_API_SECRET environment variables.'})
        
        # Create new bot instance
        bot = MultiAssetLeverageBot(api_key, api_secret, testnet)
        
        # Start trading in a separate thread
        def start_async():
            asyncio.run(bot.start_trading(capital))
        
        thread = threading.Thread(target=start_async)
        thread.start()
        
        return jsonify({'success': True, 'message': 'Live trading started successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/stop', methods=['POST'])
def stop_trading():
    global bot
    try:
        if bot:
            bot.stop_trading()
        return jsonify({'success': True, 'message': 'Trading stopped and positions liquidated'})
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
    if bot:
        return jsonify(bot.get_account_balances())
    else:
        return jsonify({
            'total_usd_value': 0,
            'balances': {},
            'error': 'Bot not initialized'
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)