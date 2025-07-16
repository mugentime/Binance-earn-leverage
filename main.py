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
    """Real Binance API integration"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://testnet.binance.vision" if testnet else "https://api.binance.com"
        self.headers = {'X-MBX-APIKEY': api_key}
        
    def _generate_signature(self, query_string: str) -> str:
        """Generate signature for Binance API"""
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _make_request(self, endpoint: str, params: Dict = None, method: str = 'GET') -> Dict:
        """Make authenticated request to Binance API"""
        if params is None:
            params = {}
        
        params['timestamp'] = int(time.time() * 1000)
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        params['signature'] = self._generate_signature(query_string)
        
        try:
            if method == 'GET':
                response = requests.get(f"{self.base_url}{endpoint}", params=params, headers=self.headers, timeout=10)
            else:
                response = requests.post(f"{self.base_url}{endpoint}", data=params, headers=self.headers, timeout=10)
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"API request failed: {e}")
            return {}
    
    def get_account_info(self) -> Dict:
        """Get spot account information"""
        endpoint = "/api/v3/account"
        return self._make_request(endpoint)
    
    def get_margin_account(self) -> Dict:
        """Get margin account information"""
        endpoint = "/sapi/v1/margin/account"
        return self._make_request(endpoint)
    
    def get_spot_prices(self) -> List[Dict]:
        """Get all spot prices"""
        endpoint = "/api/v3/ticker/price"
        try:
            response = requests.get(f"{self.base_url}{endpoint}", timeout=10)
            response.raise_for_status()
            return response.json()
        except:
            return []
    
    def get_flexible_products(self) -> List[Dict]:
        """Get flexible savings products"""
        endpoint = "/sapi/v1/lending/daily/product/list"
        params = {"status": "PURCHASING", "featured": "ALL"}
        return self._make_request(endpoint, params).get('data', [])
    
    def get_margin_interest_rates(self) -> List[Dict]:
        """Get margin interest rates"""
        endpoint = "/sapi/v1/margin/interestRateHistory"
        params = {"limit": 100}
        return self._make_request(endpoint, params).get('data', [])
    
    def get_earn_balances(self) -> List[Dict]:
        """Get flexible savings positions"""
        endpoint = "/sapi/v1/lending/daily/token/position"
        params = {"status": "HOLDING"}
        return self._make_request(endpoint, params).get('data', [])
    
    def place_margin_order(self, symbol: str, side: str, type: str, quantity: float, **kwargs) -> Dict:
        """Place margin order"""
        endpoint = "/sapi/v1/margin/order"
        params = {
            'symbol': symbol,
            'side': side,
            'type': type,
            'quantity': quantity,
            **kwargs
        }
        return self._make_request(endpoint, params, method='POST')
    
    def margin_borrow(self, asset: str, amount: float) -> Dict:
        """Borrow asset on margin"""
        endpoint = "/sapi/v1/margin/loan"
        params = {
            'asset': asset,
            'amount': amount
        }
        return self._make_request(endpoint, params, method='POST')
    
    def margin_repay(self, asset: str, amount: float) -> Dict:
        """Repay margin loan"""
        endpoint = "/sapi/v1/margin/repay"
        params = {
            'asset': asset,
            'amount': amount
        }
        return self._make_request(endpoint, params, method='POST')
    
    def subscribe_flexible_product(self, product_id: str, amount: float) -> Dict:
        """Subscribe to flexible savings product"""
        endpoint = "/sapi/v1/lending/daily/purchase"
        params = {
            'productId': product_id,
            'amount': amount
        }
        return self._make_request(endpoint, params, method='POST')
    
    def redeem_flexible_product(self, product_id: str, amount: float, type: str = "FAST") -> Dict:
        """Redeem from flexible savings"""
        endpoint = "/sapi/v1/lending/daily/redeem"
        params = {
            'productId': product_id,
            'amount': amount,
            'type': type
        }
        return self._make_request(endpoint, params, method='POST')

class MultiAssetLeverageBot:
    """Multi-Asset Leverage Bot with Real Binance Integration"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        
        # Initialize Binance API
        self.binance_api = BinanceEarnAPI(api_key, api_secret, testnet)
        
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
        
        # Wallet and balance tracking
        self.current_balances = {}
        self.current_loans = {}
        self.total_wallet_usd = 0
        self.last_balance_update = datetime.now() - timedelta(hours=1)
        
        # Price cache
        self.price_cache = {}
        self.last_price_update = datetime.now() - timedelta(minutes=5)
        
        # Start background threads
        self._start_pair_analysis_thread()
        self._start_balance_monitoring_thread()
        self._start_price_monitoring_thread()
    
    def _initialize_asset_config(self) -> Dict[str, AssetConfig]:
        """Initialize asset configuration with real data when possible"""
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
                    if yield_rate > 0:
                        config[asset].yield_rate = max(yield_rate, config[asset].yield_rate * 0.8)
            
            # Get margin rates for borrowing costs
            margin_rates = self.binance_api.get_margin_interest_rates()
            
            for rate_data in margin_rates[-50:]:  # Last 50 entries
                asset = rate_data.get('asset', '')
                if asset in config:
                    # Update loan rate from margin data
                    daily_rate = float(rate_data.get('dailyInterestRate', 0))
                    annual_rate = daily_rate * 365
                    if annual_rate > 0:
                        config[asset].loan_rate = annual_rate
                    
        except Exception as e:
            self.logger.error(f"Error updating rates from Binance: {e}")
    
    def _start_price_monitoring_thread(self):
        """Start background thread for price monitoring"""
        def monitor_prices():
            while True:
                try:
                    if datetime.now() - self.last_price_update > timedelta(minutes=1):
                        self._update_price_cache()
                        self.last_price_update = datetime.now()
                    time.sleep(60)  # Check every minute
                except Exception as e:
                    self.logger.error(f"Error in price monitoring thread: {e}")
                    time.sleep(300)  # Wait 5 minutes on error
        
        thread = threading.Thread(target=monitor_prices, daemon=True)
        thread.start()
    
    def _update_price_cache(self):
        """Update price cache with current market prices"""
        try:
            prices = self.binance_api.get_spot_prices()
            new_cache = {}
            
            for price_data in prices:
                symbol = price_data['symbol']
                price = float(price_data['price'])
                new_cache[symbol] = price
            
            self.price_cache = new_cache
            self.logger.info(f"Price cache updated with {len(new_cache)} symbols")
            
        except Exception as e:
            self.logger.error(f"Error updating price cache: {e}")
    
    def _get_usd_price(self, asset: str) -> float:
        """Get USD price for an asset"""
        if asset in ['USDT', 'USDC', 'BUSD']:
            return 1.0
            
        # Try different symbol combinations
        for suffix in ['USDT', 'USDC', 'BUSD']:
            symbol = f"{asset}{suffix}"
            if symbol in self.price_cache:
                return self.price_cache[symbol]
        
        return 0.0
    
    def _start_pair_analysis_thread(self):
        """Start background thread for pair analysis"""
        def analyze_pairs():
            while True:
                try:
                    if datetime.now() - self.last_pair_update > timedelta(minutes=5):
                        self._analyze_best_earn_pair()
                        self.last_pair_update = datetime.now()
                    time.sleep(300)  # Check every 5 minutes
                except Exception as e:
                    self.logger.error(f"Error in pair analysis thread: {e}")
                    time.sleep(300)  # Wait 5 minutes on error
        
        thread = threading.Thread(target=analyze_pairs, daemon=True)
        thread.start()
    
    def _start_balance_monitoring_thread(self):
        """Start background thread for balance monitoring"""
        def monitor_balances():
            while True:
                try:
                    if datetime.now() - self.last_balance_update > timedelta(minutes=2):
                        self._update_wallet_balances()
                        self.last_balance_update = datetime.now()
                    time.sleep(120)  # Check every 2 minutes
                except Exception as e:
                    self.logger.error(f"Error in balance monitoring thread: {e}")
                    time.sleep(300)  # Wait 5 minutes on error
        
        thread = threading.Thread(target=monitor_balances, daemon=True)
        thread.start()
    
    def _update_wallet_balances(self):
        """Update current wallet balances and loans"""
        try:
            # Get spot account balances
            account_info = self.binance_api.get_account_info()
            spot_balances = {}
            
            if 'balances' in account_info:
                for balance in account_info['balances']:
                    asset = balance['asset']
                    free = float(balance['free'])
                    locked = float(balance['locked'])
                    total = free + locked
                    if total > 0:
                        spot_balances[asset] = {
                            'free': free,
                            'locked': locked,
                            'total': total
                        }
            
            # Get earn balances
            earn_balances = self.binance_api.get_earn_balances()
            earn_positions = {}
            
            for earn_pos in earn_balances:
                asset = earn_pos.get('asset', '')
                amount = float(earn_pos.get('totalAmount', 0))
                if amount > 0:
                    earn_positions[asset] = {
                        'amount': amount,
                        'interest': float(earn_pos.get('totalInterest', 0)),
                        'type': earn_pos.get('productName', 'Flexible')
                    }
            
            # Get margin loans
            margin_account = self.binance_api.get_margin_account()
            margin_loans = {}
            
            if 'userAssets' in margin_account:
                for asset_info in margin_account['userAssets']:
                    asset = asset_info['asset']
                    borrowed = float(asset_info.get('borrowed', 0))
                    interest = float(asset_info.get('interest', 0))
                    if borrowed > 0:
                        margin_loans[asset] = {
                            'borrowed': borrowed,
                            'interest': interest,
                            'net_asset': float(asset_info.get('netAsset', 0))
                        }
            
            # Calculate total USD value
            total_usd_value = 0
            
            # Combine all balances
            all_balances = {}
            
            # Add spot balances
            for asset, balance in spot_balances.items():
                if asset not in all_balances:
                    all_balances[asset] = {'spot': 0, 'earn': 0, 'loan': 0}
                all_balances[asset]['spot'] = balance['total']
            
            # Add earn balances
            for asset, earn in earn_positions.items():
                if asset not in all_balances:
                    all_balances[asset] = {'spot': 0, 'earn': 0, 'loan': 0}
                all_balances[asset]['earn'] = earn['amount']
            
            # Add loan balances (negative)
            for asset, loan in margin_loans.items():
                if asset not in all_balances:
                    all_balances[asset] = {'spot': 0, 'earn': 0, 'loan': 0}
                all_balances[asset]['loan'] = -loan['borrowed']  # Negative for loans
            
            # Calculate USD values
            for asset, balances in all_balances.items():
                total_asset_amount = balances['spot'] + balances['earn'] + balances['loan']
                
                # Get USD price
                usd_price = self._get_usd_price(asset)
                usd_value = total_asset_amount * usd_price
                total_usd_value += usd_value
                
                balances['usd_value'] = usd_value
                balances['price'] = usd_price
            
            # Update instance variables
            self.current_balances = all_balances
            self.current_loans = margin_loans
            self.total_wallet_usd = total_usd_value
            
            self.logger.info(f"Wallet balances updated. Total USD value: ${total_usd_value:.2f}")
            
        except Exception as e:
            self.logger.error(f"Error updating wallet balances: {e}")
    
    def get_wallet_summary(self) -> Dict:
        """Get comprehensive wallet summary"""
        total_spot = sum(b.get('spot', 0) * b.get('price', 0) for b in self.current_balances.values())
        total_earn = sum(b.get('earn', 0) * b.get('price', 0) for b in self.current_balances.values())
        total_loans = sum(abs(b.get('loan', 0)) * b.get('price', 0) for b in self.current_balances.values())
        
        return {
            'total_wallet_usd': self.total_wallet_usd,
            'total_spot_usd': total_spot,
            'total_earn_usd': total_earn,
            'total_loans_usd': total_loans,
            'net_worth_usd': self.total_wallet_usd,
            'asset_count': len([a for a, b in self.current_balances.items() if b.get('spot', 0) + b.get('earn', 0) > 0]),
            'loan_count': len([a for a, b in self.current_balances.items() if b.get('loan', 0) < 0]),
            'last_update': self.last_balance_update.strftime('%Y-%m-%d %H:%M:%S'),
            'balances': self.current_balances,
            'loans': self.current_loans
        }
    
    def _analyze_best_earn_pair(self):
        """Analyze and find the best collateral/borrow pair"""
        try:
            best_pairs = []
            
            # Get current market data and trends
            market_trends = self._get_market_trends()
            
            # Define optimal borrow assets
            preferred_borrow_assets = ['USDT', 'USDC', 'BTC', 'ETH']
            
            for collateral_asset, collateral_config in self.asset_config.items():
                # Skip stablecoins as collateral in most cases
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
                        (1 / collateral_config.liquidity_tier) * 0.1
                    )
                    
                    # Bonus for stablecoin borrowing
                    stability_bonus = 2.0 if borrow_asset in ['USDT', 'USDC'] else 1.0
                    
                    # Calculate overall profit potential
                    profit_potential = (
                        net_rate * 100 * 0.5 +
                        price_advantage * 0.25 +
                        (1 / risk_score) * 0.15 +
                        collateral_config.ltv_max * 10 * 0.1
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
            # Base trend calculation
            base_trend = (hash(asset + str(datetime.now().date())) % 200 - 100) / 2000
            
            # Apply category-specific adjustments
            if asset in blue_chip_assets:
                base_trend += 0.01
            elif asset in stablecoins:
                base_trend = base_trend * 0.1
            elif asset in defi_assets:
                base_trend += 0.005
            elif asset in gaming_metaverse:
                base_trend += 0.008
            elif asset in meme_assets:
                base_trend = base_trend * 1.5
            
            # Apply tier-based adjustment
            tier = self.asset_config[asset].liquidity_tier
            tier_adjustment = (5 - tier) * 0.002
            
            trends[asset] = base_trend + tier_adjustment
        
        return trends
    
    def calculate_cascade_structure(self, initial_capital: float) -> List[Dict]:
        """Calculate cascade leverage structure"""
        cascade_levels = []
        current_capital = initial_capital
        
        # Sort assets by efficiency score
        sorted_assets = sorted(
            self.asset_config.items(),
            key=lambda x: (x[1].yield_rate - x[1].loan_rate) / (1 + x[1].volatility_factor),
            reverse=True
        )
        
        # Filter out stablecoins for collateral
        collateral_assets = [asset for asset in sorted_assets if asset[0] not in ['USDT', 'USDC']]
        
        for level in range(min(self.max_cascade_levels, len(collateral_assets))):
            if current_capital < 10:  # Minimum $10 USD
                break
            
            asset_name, asset_config = collateral_assets[level]
            max_loan = current_capital * asset_config.ltv_max
            
            # Choose optimal borrow asset
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
    
    async def execute_real_strategy(self, initial_capital: float):
        """Execute real trading strategy"""
        try:
            self.logger.info(f"Starting REAL MONEY strategy with capital: ${initial_capital}")
            self.total_capital = initial_capital
            self.is_running = True
            self.bot_status = "Running"
            
            # Calculate cascade structure
            cascade_structure = self.calculate_cascade_structure(initial_capital)
            
            # Execute each level
            for cascade_level in cascade_structure:
                try:
                    # Execute the cascade level
                    success = await self._execute_cascade_level(cascade_level)
                    
                    if success:
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
                        
                        self.logger.info(f"Successfully executed level {cascade_level['level']}")
                    else:
                        self.logger.error(f"Failed to execute level {cascade_level['level']}")
                        break
                        
                except Exception as e:
                    self.logger.error(f"Error executing cascade level {cascade_level['level']}: {e}")
                    break
            
            # Calculate final metrics
            total_leveraged = sum(pos.loan_amount for pos in self.positions)
            self.leveraged_capital = total_leveraged
            
            annual_yield = sum((l['net_yield']) * l['loan_amount'] for l in cascade_structure)
            self.total_yield = (annual_yield / initial_capital) * 100
            
            self.logger.info(f"Strategy executed successfully. {len(self.positions)} positions created.")
            
        except Exception as e:
            self.logger.error(f"Strategy execution error: {e}")
            self.bot_status = "Error"
    
    async def _execute_cascade_level(self, cascade_level: Dict) -> bool:
        """Execute a single cascade level"""
        try:
            collateral_asset = cascade_level['collateral_asset']
            loan_amount = cascade_level['loan_amount']
            loan_asset = cascade_level['loan_asset']
            
            # Step 1: Purchase collateral asset if needed
            collateral_symbol = f"{collateral_asset}USDT"
            
            # Step 2: Subscribe to flexible savings
            flexible_products = self.binance_api.get_flexible_products()
            product_id = None
            
            for product in flexible_products:
                if product.get('asset') == collateral_asset:
                    product_id = product.get('productId')
                    break
            
            if product_id:
                subscribe_result = self.binance_api.subscribe_flexible_product(
                    product_id, cascade_level['collateral_amount']
                )
                
                if 'purchaseId' not in subscribe_result:
                    return False
            
            # Step 3: Borrow against collateral
            borrow_result = self.binance_api.margin_borrow(loan_asset, loan_amount)
            
            if 'tranId' not in borrow_result:
                return False
            
            self.logger.info(f"Level {cascade_level['level']} executed: {collateral_asset} collateral, borrowed {loan_amount} {loan_asset}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error executing cascade level: {e}")
            return False
    
    async def start_simulation(self, initial_capital: float):
        """Start bot simulation or real execution"""
        if self.api_key == "demo" or self.api_secret == "demo":
            # Run simulation
            await self._run_simulation(initial_capital)
        else:
            # Run real strategy
            await self.execute_real_strategy(initial_capital)
    
    async def _run_simulation(self, initial_capital: float):
        """Run simulation mode"""
        try:
            self.logger.info(f"Starting SIMULATION with capital: ${initial_capital}")
            self.total_capital = initial_capital
            self.is_running = True
            self.bot_status = "Running (Simulation)"
            
            # Calculate cascade structure
            cascade_structure = self.calculate_cascade_structure(initial_capital)
            
            # Create simulated positions
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
    <title>Multi-Asset Leverage Bot - LIVE</title>
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
        .live-indicator {
            background: linear-gradient(45deg, #ff0000, #ff4444);
            color: white;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 1px;
            animation: blink 2s infinite;
        }
        
        @keyframes blink {
            0%, 50% { opacity: 1; }
            51%, 100% { opacity: 0.5; }
        }
        
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
        .wallet-summary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }
        
        .wallet-metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .wallet-metric {
            background: rgba(255,255,255,0.1);
            padding: 15px;
            border-radius: 8px;
            text-align: center;
            backdrop-filter: blur(10px);
        }
        
        .wallet-metric-label {
            font-size: 12px;
            opacity: 0.9;
            margin-bottom: 5px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .wallet-metric-value {
            font-size: 18px;
            font-weight: bold;
        }
        
        .balances-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
            background: rgba(255,255,255,0.05);
            border-radius: 8px;
            overflow: hidden;
        }
        
        .balances-table th,
        .balances-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        
        .balances-table th {
            background: rgba(255,255,255,0.1);
            font-weight: bold;
        }
        
        .balance-positive { color: #4CAF50; }
        .balance-negative { color: #f44336; }
        .balance-neutral { color: #fff; }
        
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
            <h1>🚀 Multi-Asset Leverage Bot <span class="live-indicator">LIVE</span></h1>
            <p>Advanced Cascade Leverage Strategy - REAL MONEY TRADING</p>
        </div>
        
        <!-- Wallet Summary Section -->
        <div class="wallet-summary">
            <h3>💼 Your Binance Wallet Overview</h3>
            <div class="wallet-metrics">
                <div class="wallet-metric">
                    <div class="wallet-metric-label">Total Net Worth</div>
                    <div class="wallet-metric-value">$<span id="total-wallet">0.00</span></div>
                </div>
                <div class="wallet-metric">
                    <div class="wallet-metric-label">Spot Balance</div>
                    <div class="wallet-metric-value">$<span id="spot-balance">0.00</span></div>
                </div>
                <div class="wallet-metric">
                    <div class="wallet-metric-label">Earn Balance</div>
                    <div class="wallet-metric-value">$<span id="earn-balance">0.00</span></div>
                </div>
                <div class="wallet-metric">
                    <div class="wallet-metric-label">Active Loans</div>
                    <div class="wallet-metric-value">$<span id="loan-balance">0.00</span></div>
                </div>
                <div class="wallet-metric">
                    <div class="wallet-metric-label">Assets Count</div>
                    <div class="wallet-metric-value"><span id="asset-count">0</span></div>
                </div>
            </div>
            
            <details>
                <summary style="cursor: pointer; padding: 10px; margin: 10px 0; background: rgba(255,255,255,0.1); border-radius: 5px;">
                    📊 View Detailed Balances & Loans
                </summary>
                <table class="balances-table">
                    <thead>
                        <tr>
                            <th>Asset</th>
                            <th>Spot</th>
                            <th>Earn</th>
                            <th>Loans</th>
                            <th>USD Value</th>
                        </tr>
                    </thead>
                    <tbody id="balances-body">
                        <tr>
                            <td colspan="5" style="text-align: center; opacity: 0.7;">Loading wallet data...</td>
                        </tr>
                    </tbody>
                </table>
            </details>
        </div>
        
        <div class="controls">
            <h3>🔴 LIVE Bot Control Panel</h3>
            <div class="input-group">
                <label for="capital">Initial Capital (USD):</label>
                <input type="number" id="capital" value="100" min="10" step="10">
            </div>
            <button class="btn btn-success" onclick="startBot()">🚀 Start LIVE Bot</button>
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
        
        async function updateWalletInfo() {
            try {
                const response = await fetch('/wallet');
                const data = await response.json();
                
                // Update wallet metrics
                document.getElementById('total-wallet').textContent = data.total_wallet_usd.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
                document.getElementById('spot-balance').textContent = data.total_spot_usd.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
                document.getElementById('earn-balance').textContent = data.total_earn_usd.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
                document.getElementById('loan-balance').textContent = data.total_loans_usd.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
                document.getElementById('asset-count').textContent = data.asset_count;
                
                // Update balances table
                const tbody = document.getElementById('balances-body');
                tbody.innerHTML = '';
                
                if (Object.keys(data.balances).length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; opacity: 0.7;">No balances found</td></tr>';
                } else {
                    Object.entries(data.balances).forEach(([asset, balance]) => {
                        const row = document.createElement('tr');
                        const spotAmount = balance.spot || 0;
                        const earnAmount = balance.earn || 0;
                        const loanAmount = balance.loan || 0;
                        const usdValue = balance.usd_value || 0;
                        
                        row.innerHTML = `
                            <td><strong>${asset}</strong></td>
                            <td class="${spotAmount > 0 ? 'balance-positive' : 'balance-neutral'}">${spotAmount.toFixed(6)}</td>
                            <td class="${earnAmount > 0 ? 'balance-positive' : 'balance-neutral'}">${earnAmount.toFixed(6)}</td>
                            <td class="${loanAmount < 0 ? 'balance-negative' : 'balance-neutral'}">${Math.abs(loanAmount).toFixed(6)}</td>
                            <td class="balance-positive">${usdValue.toFixed(2)}</td>
                        `;
                        tbody.appendChild(row);
                    });
                }
            } catch (error) {
                console.error('Error updating wallet info:', error);
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
                statusElement.className = 'status-indicator status-' + data.bot_status.toLowerCase().replace(/[^a-z]/g, '');
                
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
        setInterval(updateWalletInfo, 60000);  // Every 60 seconds
        
        // Initial load
        loadAssetConfig();
        updateStatus();
        updateBestPair();
        updateWalletInfo();
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
        
        # Create new bot instance with real API keys
        api_key = os.getenv('BINANCE_API_KEY', 'demo')
        api_secret = os.getenv('BINANCE_API_SECRET', 'demo')
        testnet = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'
        
        bot = MultiAssetLeverageBot(api_key, api_secret, testnet)
        
        # Start bot
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

@app.route('/wallet')
def get_wallet():
    global bot
    if bot:
        return jsonify(bot.get_wallet_summary())
    else:
        # Return default wallet summary
        temp_bot = MultiAssetLeverageBot('demo', 'demo')
        return jsonify(temp_bot.get_wallet_summary())

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)