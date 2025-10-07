# 🐵 Monkey Market Maven - Database Edition

<div align="center">

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Discord.py](https://img.shields.io/badge/discord.py-2.3+-7289DA.svg)
![SQLite](https://img.shields.io/badge/SQLite-3-003B57.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

**虛擬股票交易機器人 - 完全重構資料庫版本**

一群完全不會程式的樂子人，妄想透過 AI 做出虛擬交易機器人。
現在有了專業的資料庫架構！

</div>

---

## 🎯 專案特色

### ✨ 新版本亮點

- **🗄️ SQLite 資料庫** - 取代 CSV 檔案，更穩定、更快速
- **🧩 模組化架構** - 使用 Discord.py Cogs 組織程式碼
- **⚡ 非同步處理** - 完整的 async/await 架構
- **👤 使用者設定** - 每個用戶可自訂交易偏好
- **📊 完整日誌** - 所有操作都有完整紀錄
- **🔒 資料完整性** - ACID 交易保證

### 🎮 核心功能

1. **虛擬股票交易** - 買入、賣出、隨機選股
2. **投資組合管理** - 庫存追蹤、成本調整
3. **損益計算** - 自動計算手續費、證交稅和損益
4. **猴子交易系統** - 加權隨機自動交易模擬
5. **即時股價查詢** - 台灣證交所 API 整合

---

## 📋 系統需求

- Python 3.9 或更高版本
- Discord Bot Token
- Google Cloud VM 或任何支援 Python 的伺服器

---

## 🚀 快速開始

### 1. 克隆專案

```bash
git clone https://github.com/yourusername/monkey-market-maven.git
cd monkey-market-maven
```

### 2. 安裝相依套件

```bash
pip install -r requirements.txt
```

### 3. 設定環境變數

建立 `.env` 檔案：

```env
TOKEN=your_discord_bot_token_here
```

### 4. 建立專案結構

```bash
# 建立必要的目錄和初始化檔案
mkdir -p database cogs utils
touch database/__init__.py
touch cogs/__init__.py
touch utils/__init__.py
```

### 5. 測試資料庫

```bash
python test_database.py
```

如果所有測試通過，您的資料庫設定就完成了！

### 6. 啟動機器人

```bash
python main.py
```

---

## 📁 專案結構

```
monkey-market-maven/
│
├── main.py                      # 機器人主程式
├── .env                         # 環境變數 (請勿提交)
├── .gitignore                   # Git 忽略檔案
├── requirements.txt             # Python 套件清單
├── README.md                    # 專案說明文件
├── 上市股票.csv                  # 台灣上市股票清單
│
├── database/                    # 資料庫層
│   ├── __init__.py
│   └── schema.py                # 資料庫架構與管理
│
├── cogs/                        # 指令模組
│   ├── __init__.py
│   ├── general.py               # 幫助與通用指令
│   ├── trading.py               # 買賣交易指令
│   ├── portfolio.py             # 投資組合管理
│   ├── profit.py                # 損益追蹤
│   ├── monkey.py                # 猴子交易系統
│   └── settings.py              # 使用者設定
│
├── utils/                       # 工具函式
│   ├── __init__.py
│   └── stock_utils.py           # 股票資料處理
│
├── test_database.py             # 資料庫測試腳本
├── migrate_csv_to_db.py         # CSV 轉資料庫工具
│
└── trading_bot.db               # SQLite 資料庫 (自動生成)
```

---

## 💾 資料庫架構

### 資料表總覽

| 資料表 | 用途 | 關鍵欄位 |
|--------|------|----------|
| `portfolio` | 持股庫存 | user_id, stock_code, shares, total_cost |
| `transactions` | 交易日誌 | user_id, timestamp, transaction_type, amount |
| `profit_loss` | 損益紀錄 | user_id, profit_loss, buy_price, sell_price |
| `user_settings` | 使用者設定 | user_id, monkey_min_amount, monkey_weights |
| `pending_trades` | 待確認交易 | user_id, stock_code, shares, price |
| `monkey_sell_state` | 猴子賣出狀態 | user_id, shares_to_sell, average_cost |

### 資料流程

```
舊版 CSV 流程:
User → Command → Read CSV → Process → Write CSV → Response

新版資料庫流程:
User → Command → Query DB → Process → Update DB → Response
```

**優勢:**
- ✅ 支援並發存取 (WAL 模式)
- ✅ 資料完整性保證 (ACID)
- ✅ 複雜查詢能力 (SQL)
- ✅ 更好的效能
- ✅ 更容易維護

---

## 🎮 指令列表

### 📈 交易指令

| 指令 | 說明 | 範例 |
|------|------|------|
| `!random` | 隨機選股並產生交易 | `!random` |
| `!ry` | 確認隨機交易 | `!ry` |
| `!rn` | 取消隨機交易 | `!rn` |
| `!buy <股票> <股數> [價格]` | 買入股票 | `!buy 2330 10` 或 `!buy 台積電 10 600` |
| `!sell <股票> <股數> [價格]` | 賣出股票 | `!sell 2330 5` 或 `!sell 0050 10 150` |

### 💼 投資組合

| 指令 | 說明 | 範例 |
|------|------|------|
| `!summary` | 顯示庫存摘要 | `!summary` |
| `!adjust_cost <股票> <新成本>` | 調整持股成本 | `!adjust_cost 2330 580` |
| `!show [數量]` | 顯示最近操作 | `!show` 或 `!show 10` |

### 💰 損益管理

| 指令 | 說明 | 範例 |
|------|------|------|
| `!profit` | 查看總已實現損益 | `!profit` |
| `!profitclear` | 清空損益紀錄 | `!profitclear` |

### 🐵 猴子交易

| 指令 | 說明 | 範例 |
|------|------|------|
| `!monkey [最小] [最大]` | 讓猴子隨機交易 | `!monkey` 或 `!monkey 10000 50000` |
| `!usersetting` | 查看交易設定 | `!usersetting` |
| `!usersetting amount <最小> <最大>` | 設定金額範圍 | `!usersetting amount 5000 30000` |
| `!usersetting weights <買> <賣> <持有>` | 設定操作權重 | `!usersetting weights 40 30 30` |
| `!usersetting reset` | 重置為預設值 | `!usersetting reset` |

### 📚 其他指令

| 指令 | 說明 | 範例 |
|------|------|------|
| `!bothelp` | 顯示完整說明 | `!bothelp` |
| `!info` | 機器人資訊 | `!info` |
| `!ping` | 檢查延遲 | `!ping` |

---

## 💡 使用範例

### 基本交易流程

```
# 1. 以市價買入台積電
!buy 2330 10

# 2. 以自訂價格買入 0050
!buy 0050 20 150

# 3. 查看庫存
!summary

# 4. 賣出股票
!sell 2330 5

# 5. 查看損益
!profit
