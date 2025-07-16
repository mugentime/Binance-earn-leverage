# Multi-Asset Leverage Bot - LIVE TRADING

🚀 **Real Money Trading Bot - Advanced Cascade Leverage Strategy**

Production-ready application that executes real trades on Binance using automated cascade leverage strategy to maximize capital efficiency.

## 🎯 Live Trading Strategy

### Concept Principal
- **Cascade Leverage**: Each loan generates new collateral for the next level
- **Multi-Asset**: Uses 25+ assets organized in 4 liquidity tiers
- **Real Execution**: Places actual trades with real money
- **Risk Management**: Automated liquidation and monitoring

### Asset Tiers
- **Tier 1**: BTC, ETH, BNB, USDT, USDC (High liquidity, LTV 65-85%)
- **Tier 2**: CVX, ZRX, ETHFI, HIFI (Medium liquidity, LTV 40-55%)
- **Tier 3**: ONT, LIT, LSK, SKL, GLMR, RIF, FLM, STPT, DUSK (LTV 30-45%)
- **Tier 4**: BNX, BOME, OXT, RONIN, WIF, XVG (High yield, LTV 22-35%)

## 📊 Performance Targets

With **$1,000 initial capital**:
- **Total leveraged capital**: ~$2,400
- **Effective leverage**: 2.4x
- **Target ROI**: 13-15% annually
- **Expected returns**: $130-150/year

## 🛠️ Live Trading Features

### ✅ Production Ready
- [x] **Real Binance API Integration**
- [x] **Actual order execution** with market prices
- [x] **Margin trading** and borrowing
- [x] **Flexible savings** for additional yield
- [x] **Emergency liquidation** system
- [x] **Real-time monitoring** every 30 seconds
- [x] **Position tracking** with order IDs
- [x] **Risk management** with LTV monitoring

### 🚀 Deployment

**Required Environment Variables:**
```
BINANCE_API_KEY=your_real_api_key
BINANCE_API_SECRET=your_real_secret
BINANCE_TESTNET=false
FLASK_ENV=production
```

**Deploy to Railway:**
1. Set environment variables in Railway dashboard
2. Push code to repository
3. Railway auto-deploys using Dockerfile
4. Access dashboard at your Railway URL

## 🎯 How It Works

### Real Trading Process
1. **Account Verification**: Checks Binance balances and permissions
2. **Asset Purchase**: Buys crypto with USDT using market orders
3. **Margin Transfer**: Moves assets to margin account
4. **Borrowing**: Takes USDT loans against collateral
5. **Cascade Execution**: Repeats process up to 5 levels
6. **Yield Optimization**: Deposits assets in flexible savings

### Risk Controls
- **Maximum LTV**: 85% emergency liquidation
- **Position Monitoring**: Real-time price tracking
- **Auto-liquidation**: Automatic position closure
- **Balance Verification**: Insufficient fund protection

## 💼 Dashboard Features

### Account Overview
- **Total portfolio value** in real-time
- **Available USDT** balance
- **Active trading positions**
- **Total outstanding loans**

### Live Controls
- **START LIVE TRADING**: Execute real trades
- **STOP & LIQUIDATE ALL**: Emergency position closure
- **Real-time status** updates every 15 seconds

### Position Tracking
- **Level-by-level** position details
- **Collateral amounts** and loan values
- **Current LTV ratios**
- **Real order IDs** from Binance

## 🔐 Security Requirements

### Binance API Setup
**Required Permissions:**
- ✅ Enable Reading
- ✅ Enable Spot & Margin Trading  
- ✅ Enable Margin
- ✅ Enable Savings

**Security Settings:**
- Whitelist your deployment server IP
- Use strong API credentials
- Never share API keys

### Minimum Requirements
- **$50+ USDT** in spot wallet
- **Margin trading** enabled on Binance
- **Identity verification** completed
- **API permissions** properly configured

## ⚡ Real Trading Workflow

1. **Initialize**: Bot connects to Binance and verifies account
2. **Capital Deployment**: Executes cascade strategy with real orders
3. **Monitoring**: Continuously tracks positions and market prices
4. **Risk Management**: Automatic liquidation if LTV exceeds limits
5. **Yield Generation**: Earnings from lending spreads and flexible savings

## 🛡️ Risk Management

### Automated Protection
- **LTV Monitoring**: Continuous ratio tracking
- **Emergency Stops**: Automatic liquidation at 85% LTV
- **Position Limits**: Maximum 5 cascade levels
- **Balance Checks**: Prevents overdeployment

### Manual Controls
- **Instant Stop**: Emergency liquidation button
- **Real-time Dashboard**: Live position monitoring
- **Order Tracking**: Full audit trail with Binance order IDs

## 📈 Live Performance Metrics

The dashboard shows:
- **Real portfolio value** from Binance balances
- **Actual loan amounts** and interest rates
- **Live LTV ratios** for each position
- **Current yield estimates** based on real rates
- **Order execution** status and timing

## 🚨 Important Notes

This bot executes **real trades with real money**:
- Start with small amounts to test
- Monitor positions actively
- Understand liquidation risks
- Only invest what you can afford to lose

---

**⚡ Live Trading Ready | 🔴 Real Money Operations**