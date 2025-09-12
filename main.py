import discord
from discord.ext import commands, tasks
import os
import csv
from datetime import datetime, date, timedelta
import random
import pandas as pd
from dotenv import load_dotenv
import requests
import asyncio
from pathlib import Path  # 引入 pathlib 方便處理路徑
#最底部新增每月將舊的資料開資料夾個別儲存降低使用中資料的複雜度，但最後寫入格式八成有點問題... by za 20250910_0044
# ---------- 設定 ----------
load_dotenv()
STOCK_LIST_FILE = "上市股票.csv"
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    print("錯誤：找不到 Discord Bot Token。請檢查您的 .env 檔案或環境變數設定。")
    exit()

MONKEY_WEIGHTS = {"buy": 35, "sell": 30, "hold": 35}

# ---------- Discord Bot 初始化 ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- 全域變數 ----------
pending_trades = {}
stock_data = {}
monkey_sell_state = {}
is_archiving = False  # 用於標記是否正在進行每月歸檔


# ---------- 輔助函式 ----------
def load_stock_data():
    """從 CSV 載入股票代碼和名稱到記憶體中"""
    global stock_data
    try:
        with open(STOCK_LIST_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader)  # 跳過標頭
            stock_data = {
                row[0].strip(): row[1].strip()
                for row in reader if len(row) >= 2
            }
        print(f"成功載入 {len(stock_data)} 筆股票資料。")
    except FileNotFoundError:
        print(f"錯誤：找不到股票清單檔案 `{STOCK_LIST_FILE}`。")
        stock_data = {}
    except Exception as e:
        print(f"載入股票資料時發生錯誤: {e}")
        stock_data = {}


def get_stock_info(identifier: str) -> tuple:
    """根據代碼或名稱查找股票資訊"""
    if identifier.isdigit() and len(
            identifier) == 4 and identifier in stock_data:
        return identifier, stock_data[identifier]
    for code, name in stock_data.items():
        if name == identifier:
            return code, name
    return None, None


def get_user_csv_path(user_id: str) -> str:
    """根據使用者 ID 取得其 CSV 檔案路徑"""
    return f"{user_id}.csv"


def create_user_csv_if_not_exists(user_id: str):
    """
    如果使用者的 CSV 檔案不存在，則建立它並寫入標頭。
    此函式是確保所有 CSV 標頭一致的關鍵。
    """
    file_path = get_user_csv_path(user_id)
    if not os.path.exists(file_path):
        with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(
                ["操作時間", "指令", "類別", "股票代碼", "股票名稱", "股數", "股價", "金額", "損益"])


def log_to_user_csv(user_id: str,
                    command: str,
                    category: str,
                    stock_code: str,
                    stock_name: str,
                    shares: int,
                    price: float,
                    amount: float,
                    profit_loss: float = None):
    """將一筆紀錄寫入指定使用者的 CSV"""
    file_path = get_user_csv_path(user_id)
    with open(file_path, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        profit_loss_value = profit_loss if profit_loss is not None else ''
        writer.writerow([
            timestamp, command, category, stock_code, stock_name, shares,
            price, amount, profit_loss_value
        ])


def get_user_data(user_id: str, file_path: str = None) -> pd.DataFrame:
    """讀取並回傳使用者的 CSV 資料 (使用 pandas)，可指定路徑"""
    path = file_path if file_path else get_user_csv_path(user_id)
    if not os.path.exists(path):
        return pd.DataFrame()
    # 確保讀取時股票代碼為字串格式，避免 '0050' 變為 50
    return pd.read_csv(path, dtype={'股票代碼': str})


def get_stock_price(stock_id: str) -> float:
    """從台灣證券交易所 API 取得即時股價"""
    url = f'https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{stock_id}.tw&json=1'
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        res.raise_for_status()  # 若請求失敗則拋出錯誤
        data = res.json()
        msg = data.get('msgArray', [])
        if msg:
            price_str = msg[0].get('z')
            if price_str in (None, '-', ''):
                price_str = msg[0].get('o')  # 若無成交價則取開盤價
            if price_str in (None, '-', ''):
                price_str = msg[0].get('y')  #若無成交價也無開盤價，抓取昨收價
            if price_str and price_str not in (None, '-', '', '無資料'):
                return round(float(price_str), 2)
        return 0.0
    except requests.exceptions.RequestException as e:
        print(f"取得 {stock_id} 股價時網路請求失敗: {e}")
        return 0.0
    except Exception as e:
        print(f"解析或取得 {stock_id} 股價資料時失敗: {e}")
        return 0.0


# ---------- Bot 事件 ----------


@bot.event
async def on_ready():
    print(f'機器人 {bot.user} 已成功登入！')
    load_stock_data()
    monthly_archive.start()  # 啟動每月歸檔的背景任務


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error,
                  (commands.MissingRequiredArgument, commands.BadArgument)):
        await ctx.send("指令參數錯誤，請檢查後再試一次。")
    elif not isinstance(error, commands.CommandNotFound):
        print(f"發生錯誤: {error}")
        await ctx.send("執行指令時發生未知的錯誤。")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # 檢查是否正在歸檔，若是則暫停服務
    if is_archiving:
        await message.channel.send("系統正在進行每月資料整理，請稍後再試。", delete_after=10)
        return

    user_id = message.author.id
    # 優先處理猴子賣出狀態
    if user_id in monkey_sell_state:
        # (此處為猴子狀態處理邏輯，與前版本相同)
        try:
            price_input = float(message.content)
            if price_input <= 0:
                await message.channel.send("價格必須是正數，請重新輸入：", delete_after=10)
                return
            await message.add_reaction('✅')
            state_data = monkey_sell_state.pop(user_id)

            sell_price = price_input
            stock_code, stock_name, shares_to_sell, avg_cost = state_data[
                "stock_code"], state_data["stock_name"], state_data[
                    "shares_to_sell"], state_data["average_cost"]
            sell_amount = round(shares_to_sell * sell_price, 2)
            profit_loss = round((sell_price - avg_cost) * shares_to_sell, 2)

            log_to_user_csv(str(user_id), "!monkey", "庫存", stock_code,
                            stock_name, -shares_to_sell, sell_price,
                            -sell_amount)
            log_to_user_csv(str(user_id), "!monkey", "操作", stock_code,
                            stock_name, -shares_to_sell, sell_price,
                            sell_amount)
            log_to_user_csv(str(user_id),
                            "!monkey",
                            "損益",
                            stock_code,
                            stock_name,
                            shares_to_sell,
                            sell_price,
                            sell_amount,
                            profit_loss=profit_loss)
            await message.channel.send(
                f"🙈 **賣出！** 猴子已遵照您的指示賣出 **{stock_name}({stock_code})**！")
        except ValueError:
            await message.channel.send("格式錯誤，請輸入有效的數字價格：", delete_after=10)
        except Exception as e:
            if user_id in monkey_sell_state: del monkey_sell_state[user_id]
            await message.channel.send(f"處理賣出時發生錯誤: {e}")
        return

    # 接著處理一般邏輯
    str_user_id = str(user_id)
    if str_user_id in pending_trades and not message.content.startswith(
        ('!ry', '!rn')):
        await message.channel.send(
            f"{message.author.mention}，您有一筆隨機選股交易待確認，請先使用 `!ry` 或 `!rn` 回覆。")
        return

    await bot.process_commands(message)


# (此處省略 !bothelp, !random, !ry, !rn, !buy, !sell, !profit 等不變的指令)
# ...
@bot.command(name="bothelp")
async def _bothelp(ctx):
    embed = discord.Embed(title="🤖 指令說明書",
                          description="以下是所有可用的指令：",
                          color=discord.Color.orange())
    embed.add_field(name="`!random`",
                    value="隨機挑選一支股票並產生一筆模擬交易，等待您確認。",
                    inline=False)
    embed.add_field(name="`!ry`",
                    value="確認由 `!random` 產生的交易，執行買入。",
                    inline=False)
    embed.add_field(name="`!rn`", value="取消由 `!random` 產生的交易。", inline=False)
    embed.add_field(name="`!buy <股票> <股數>`",
                    value="買入指定數量的特定股票。",
                    inline=False)
    embed.add_field(name="`!sell <股票> <股數> [價格]`",
                    value="賣出股票，可選填自訂價格進行損益結算。",
                    inline=False)
    embed.add_field(name="`!summary [股票] [新成本]`",
                    value="顯示庫存，或輸入股票與新成本來調整持有成本。",
                    inline=False)
    embed.add_field(name="`!show`", value="顯示最近 5 筆的操作紀錄。", inline=False)
    embed.add_field(name="`!profit`", value="計算並顯示您所有已實現的總損益。", inline=False)
    embed.add_field(name="`!profitclear`",
                    value="將您已實現的總損益紀錄歸零。",
                    inline=False)
    embed.add_field(name="`!monkey [最小金額] [最大金額]`",
                    value="讓猴子為您操盤！可自訂金額範圍 (每日一次)。",
                    inline=False)
    embed.set_footer(text="請將 <...> 替換為實際的參數，[...] 為選擇性參數")
    await ctx.send(embed=embed)


@bot.command(name="random")
async def _random(ctx):
    user_id = str(ctx.author.id)
    create_user_csv_if_not_exists(user_id)
    if not stock_data:
        await ctx.send("錯誤：股票資料未載入，無法執行隨機選股。")
        return
    stock_code, stock_name = random.choice(list(stock_data.items()))
    stock_price = get_stock_price(stock_code)
    amount = random.randrange(5000, 100001, 1000)
    if stock_price <= 0:
        await ctx.send(f"無法取得 {stock_name}({stock_code}) 的有效股價，請稍後再試。")
        return
    shares = int(amount // stock_price)
    if shares == 0:
        await ctx.send(
            f"以 {amount} 元的預算，在股價 {stock_price} 的情況下，無法購買至少一股 {stock_name}({stock_code})。請再試一次！"
        )
        return
    total_amount = round(shares * stock_price, 2)
    pending_trades[user_id] = {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "shares": shares,
        "price": stock_price,
        "amount": total_amount
    }
    embed = discord.Embed(title="🎲 隨機選股產生器", color=discord.Color.blue())
    embed.add_field(name="股票",
                    value=f"{stock_name}({stock_code})",
                    inline=False)
    embed.add_field(name="股數", value=f"{shares} 股", inline=True)
    embed.add_field(name="股價", value=f"${stock_price:,.2f}", inline=True)
    embed.add_field(name="總金額", value=f"${total_amount:,.2f}", inline=False)
    embed.set_footer(text="是否買入? 請使用 !ry (是) 或 !rn (否) 指令回覆。")
    await ctx.send(embed=embed)


@bot.command(name="ry")
async def _ry(ctx):
    user_id = str(ctx.author.id)
    if user_id in pending_trades:
        trade = pending_trades.pop(user_id)
        log_to_user_csv(user_id, "!random -> !ry", "庫存", trade["stock_code"],
                        trade["stock_name"], trade["shares"], trade["price"],
                        trade["amount"])
        log_to_user_csv(user_id, "!random -> !ry", "操作", trade["stock_code"],
                        trade["stock_name"], trade["shares"], trade["price"],
                        trade["amount"])
        await ctx.send(
            f"✅ **購買成功！** 已將 **{trade['stock_name']}({trade['stock_code']})** 加入您的庫存。"
        )
    else:
        await ctx.send("您沒有待確認的購買交易。")


@bot.command(name="rn")
async def _rn(ctx):
    user_id = str(ctx.author.id)
    if user_id in pending_trades:
        pending_trades.pop(user_id)
        await ctx.send("👌 交易已取消。")
    else:
        await ctx.send("您沒有待確認的購買交易。")


@bot.command(name="buy")
async def _buy(ctx, stock_identifier: str, shares_to_buy: int):
    user_id = str(ctx.author.id)
    create_user_csv_if_not_exists(user_id)
    stock_code, stock_name = get_stock_info(stock_identifier)
    if not stock_code:
        await ctx.send(f"❌ 找不到股票 `{stock_identifier}`。請確認股票代碼或名稱是否正確。")
        return
    if shares_to_buy <= 0:
        await ctx.send("❌ 購買股數必須為正整數。")
        return
    current_price = get_stock_price(stock_code)
    if current_price <= 0:
        await ctx.send(f"❌ 無法取得 **{stock_name}({stock_code})** 的即時股價，無法完成購買。")
        return
    buy_amount = round(shares_to_buy * current_price, 2)
    log_to_user_csv(user_id, "!buy", "庫存", stock_code, stock_name,
                    shares_to_buy, current_price, buy_amount)
    log_to_user_csv(user_id, "!buy", "操作", stock_code, stock_name,
                    shares_to_buy, current_price, buy_amount)
    await ctx.send(
        f"✅ **購買成功！** 您已購買了 {shares_to_buy} 股 **{stock_name}({stock_code})** ，買入股價為 **{current_price}** 元。"
    )


@_buy.error
async def buy_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("指令參數不足！請使用 `!buy <股票代碼/名稱> <股數>` 格式。")


@bot.command(name="sell")
async def _sell(ctx,
                stock_identifier: str,
                shares_to_sell: int,
                custom_price: float = None):
    user_id = str(ctx.author.id)
    create_user_csv_if_not_exists(user_id)

    stock_code, stock_name = get_stock_info(stock_identifier)
    if not stock_code:
        await ctx.send(f"❌ 找不到股票 `{stock_identifier}`。請確認股票代碼或名稱是否正確。")
        return

    if shares_to_sell <= 0:
        await ctx.send("❌ 賣出股數必須為正整數。")
        return

    if custom_price is not None and custom_price <= 0:
        await ctx.send("❌ 自訂價格必須為正數。")
        return

    df = get_user_data(user_id)
    inventory = df[df['類別'] == '庫存']
    stock_inventory = inventory[inventory['股票代碼'] == stock_code]
    current_shares = stock_inventory['股數'].sum()

    if current_shares < shares_to_sell:
        await ctx.send(
            f"❌ 操作失敗：您的庫存中只有 {int(current_shares)} 股 **{stock_name}({stock_code})**，不足以賣出 {shares_to_sell} 股。"
        )
        return

    if custom_price is not None:
        current_price = custom_price
        price_source_text = "(使用自訂價格)"
    else:
        current_price = get_stock_price(stock_code)
        price_source_text = "(使用即時市價)"

    if current_price <= 0:
        await ctx.send(f"❌ 無法取得 **{stock_name}({stock_code})** 的有效股價，無法完成賣出。")
        return

    total_cost = stock_inventory['金額'].sum()
    average_cost_price = total_cost / current_shares
    sell_amount = round(shares_to_sell * average_cost_price, 2)
    profit_loss = round((current_price - average_cost_price) * shares_to_sell,
                        2)

    log_to_user_csv(user_id, "!sell", "庫存", stock_code, stock_name,
                    -shares_to_sell, current_price, -sell_amount)
    log_to_user_csv(user_id, "!sell", "操作", stock_code, stock_name,
                    -shares_to_sell, current_price, sell_amount)
    log_to_user_csv(user_id,
                    "!sell",
                    "損益",
                    stock_code,
                    stock_name,
                    shares_to_sell,
                    current_price,
                    sell_amount,
                    profit_loss=profit_loss)

    profit_loss_color = discord.Color.green(
    ) if profit_loss >= 0 else discord.Color.red()
    embed = discord.Embed(title="✅ 賣出成功！", color=profit_loss_color)
    embed.description = f"您已賣出 {shares_to_sell} 股 **{stock_name}({stock_code})**。"
    embed.add_field(name=f"賣出價格 {price_source_text}",
                    value=f"${current_price:,.2f}",
                    inline=True)
    embed.add_field(name="平均成本",
                    value=f"${average_cost_price:,.2f}",
                    inline=True)
    embed.add_field(name="損益", value=f"**${profit_loss:,.2f}**", inline=False)

    await ctx.send(embed=embed)

@bot.command(name="summary")
async def _summary(ctx, stock_identifier: str = None, new_cost: float = None):
    user_id = str(ctx.author.id)
    create_user_csv_if_not_exists(user_id)

    # === 成本調整邏輯 ===
    if stock_identifier and new_cost:
        if new_cost <= 0:
            await ctx.send("❌ 新的成本必須是正數。")
            return
        stock_code, stock_name = get_stock_info(stock_identifier)
        if not stock_code:
            await ctx.send(f"❌ 在您的庫存中找不到股票 `{stock_identifier}`。")
            return

        df = get_user_data(user_id)
        inventory = df[df['類別'] == '庫存']
        stock_inventory = inventory[inventory['股票代碼'] == stock_code]
        current_shares = stock_inventory['股數'].sum()

        if current_shares > 0:
            current_total_cost = stock_inventory['金額'].sum()
            new_total_cost = new_cost * current_shares
            cost_adjustment = new_total_cost - current_total_cost

            log_to_user_csv(
                user_id, "!summary (adjust)", "庫存",
                stock_code, stock_name, 0, 0,
                cost_adjustment
            )
            await ctx.send(
                f"✅ 已將 **{stock_name}({stock_code})** 的平均成本調整為 **${new_cost:,.2f}**。"
            )
        else:
            await ctx.send(
                f"❌ 您目前未持有 **{stock_name}({stock_code})**，無法調整成本。"
            )
        return
    elif stock_identifier or new_cost:
        await ctx.send("❌ 參數錯誤！若要調整成本，必須同時提供 `股票代碼/名稱` 和 `新的平均成本`。")
        return

    # === 讀取庫存 ===
    df = get_user_data(user_id)
    inventory = df[df['類別'] == '庫存']
    if inventory.empty:
        await ctx.send("您的庫存目前是空的。")
        return

    summary_data = inventory.groupby(['股票代碼', '股票名稱']).agg(
        股數=('股數', 'sum'),
        總成本=('金額', 'sum')
    ).reset_index()
    summary_data = summary_data[summary_data['股數'] > 0]
    if summary_data.empty:
        await ctx.send("您的庫存目前是空的。")
        return

    total_cost = total_value = total_profit_loss = total_shares = 0
    stock_details = []

    for _, row in summary_data.iterrows():
        current_price = get_stock_price(row['股票代碼'])
        avg_cost = row['總成本'] / row['股數']

        if current_price > 0:
            current_value = row['股數'] * current_price
            profit_loss = current_value - row['總成本']
            profit_percentage = (profit_loss / row['總成本']) * 100

            total_cost += row['總成本']
            total_value += current_value
            total_profit_loss += profit_loss
            total_shares += row['股數']

            stock_details.append({
                'name': row['股票名稱'],
                'code': row['股票代碼'],
                'shares': int(row['股數']),
                'avg_price': avg_cost,
                'current_price': current_price,
                'market_value': current_value,
                'profit_loss': profit_loss,
                'profit_percentage': profit_percentage,
                'has_price': True
            })
        else:
            total_cost += row['總成本']
            total_shares += row['股數']
            stock_details.append({
                'name': row['股票名稱'],
                'code': row['股票代碼'],
                'shares': int(row['股數']),
                'avg_price': avg_cost,
                'current_price': None,
                'market_value': None,
                'profit_loss': None,
                'profit_percentage': None,
                'has_price': False
            })

    # === 建立表格 Embed ===
    embed = discord.Embed(
        title=f"📊 {ctx.author.display_name} 的投資組合摘要",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )

    table_header = "股票代碼/名稱      股數    均價     現價     市值        損益       報酬率\n"
    table_header += "─" * 80
    table_rows = []

    for stock in stock_details:
        name_code = f"{stock['name']}({stock['code']})"
        if stock['has_price']:
            profit_emoji = "🟢" if stock['profit_loss'] >= 0 else "🔴"
            row = (
                f"{name_code:<16} "
                f"{stock['shares']:>6,}股  "
                f"${stock['avg_price']:>7.2f}  "
                f"${stock['current_price']:>7.2f}  "
                f"${stock['market_value']:>9,.2f}  "
                f"{profit_emoji}${stock['profit_loss']:>+8,.2f}  "
                f"{profit_emoji}{stock['profit_percentage']:>+6.2f}%"
            )
        else:
            row = (
                f"{name_code:<16} "
                f"{stock['shares']:>6,}股  "
                f"${stock['avg_price']:>7.2f}  "
                f"   無現價    無市值    無損益    無報酬率"
            )
        table_rows.append(row)

    # 總計
    if total_value > 0:
        profit_percentage = (total_profit_loss / total_cost) * 100 if total_cost > 0 else 0
        profit_emoji = "🟢" if total_profit_loss >= 0 else "🔴"
        total_avg_price = total_cost / total_shares if total_shares > 0 else 0
        total_row = (
            f"{'總計':<16} "
            f"{total_shares:>6,}股  "
            f"${total_avg_price:>7.2f}  "
            f"{'':>7}  "
            f"${total_value:>9,.2f}  "
            f"{profit_emoji}${total_profit_loss:>+8,.2f}  "
            f"{profit_emoji}{profit_percentage:>+6.2f}%"
        )
        table_rows.append("─" * 80)
        table_rows.append(total_row)

    embed.add_field(
        name="📋 持股明細",
        value=f"```\n{table_header}\n" + "\n".join(table_rows) + "\n```",
        inline=False
    )

    embed.set_footer(
        text="💡 使用 !summary <股票> <新成本> 調整平均成本",
        icon_url=ctx.author.avatar.url if ctx.author.avatar else None
    )

    await ctx.send(embed=embed)




@bot.command(name="show")
async def _show(ctx):
    user_id = str(ctx.author.id)
    create_user_csv_if_not_exists(user_id)

    df_current = get_user_data(user_id)
    operations_current = df_current[df_current['類別'] == '操作']

    combined_ops = operations_current

    # 若當前紀錄不足5筆，嘗試從歸檔資料補充
    if len(operations_current) < 5:
        needed = 5 - len(operations_current)
        user_archive_dir = Path(user_id)

        if user_archive_dir.is_dir():
            archive_files = sorted(user_archive_dir.glob('*_archive.csv'),
                                   reverse=True)
            if archive_files:
                latest_archive_path = archive_files[0]
                df_archive = get_user_data(user_id,
                                           file_path=str(latest_archive_path))
                operations_archive = df_archive[df_archive['類別'] == '操作'].tail(
                    needed)
                combined_ops = pd.concat(
                    [operations_archive, operations_current])

    final_ops = combined_ops.tail(5)

    if final_ops.empty:
        await ctx.send("最近沒有任何操作紀錄。")
        return

    response = f"**{ctx.author.display_name} 的最近 5 筆操作紀錄：**\n```\n"
    for _, row in final_ops.iterrows():
        action = "買入" if row['股數'] > 0 else "賣出"
        response += f"時間: {row['操作時間']}, 指令: {row['指令']}, 動作: {action}, 股票: {row['股票名稱']}({row['股票代碼']}), 股數: {abs(int(row['股數']))}\n"
    response += "```"
    await ctx.send(response)

@bot.command(name="profit")
async def _profit(ctx):
    user_id = str(ctx.author.id)
    create_user_csv_if_not_exists(user_id)
    df = get_user_data(user_id)
    if '損益' not in df.columns or df[df['類別'] == '損益'].empty:
        await ctx.send("目前沒有任何已實現的損益紀錄。")
        return
    profit_df = df[df['類別'] == '損益']
    total_profit = profit_df['損益'].sum()
    color = discord.Color.green() if total_profit >= 0 else discord.Color.red()
    title = "📈 總已實現損益" if total_profit >= 0 else "📉 總已實現損益"
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name=f"{ctx.author.display_name} 的總損益為：", value=f"**${total_profit:,.2f}**")
    await ctx.send(embed=embed)

@bot.command(name="profitclear")
async def _profitclear(ctx):
    user_id = str(ctx.author.id)
    create_user_csv_if_not_exists(user_id)
    df = get_user_data(user_id)
    if '損益' not in df.columns or df[df['類別'] == '損益'].empty:
        await ctx.send("您目前沒有任何損益紀錄可歸零。")
        return
    profit_df = df[df['類別'] == '損益']
    total_profit = profit_df['損益'].sum()
    if total_profit == 0:
        await ctx.send("您的總損益已經是 0，無需歸零。")
        return
    log_to_user_csv(user_id, "!profitclear", "損益", "SYSTEM", "損益歸零", 0, 0, 0, profit_loss=-total_profit)
    await ctx.send(f"✅ **損益已歸零！** 已新增一筆 ${-total_profit:,.2f} 的紀錄來平衡您的總損益。")



@bot.command(name="monkey")
async def _monkey(ctx, *args):
    user_id = ctx.author.id
    str_user_id = str(user_id)
    create_user_csv_if_not_exists(str_user_id)

    # ========== 冷卻開關 ==========
    ENABLE_COOLDOWN = False  # True = 啟用冷卻 (一天一次) / False = 禁用冷卻 (無限次)
    # =============================

    if ENABLE_COOLDOWN:
        # 原有的冷卻檢查邏輯
        df_user = get_user_data(str_user_id)
        cooldown_logs = df_user[(df_user['類別'] == '系統紀錄')
                                & (df_user['股票代碼'] == 'MONKEY_CD')]
        if not cooldown_logs.empty:
            last_used_str = cooldown_logs.iloc[-1]['操作時間']
            last_used_date = datetime.strptime(last_used_str,
                                               '%Y-%m-%d %H:%M:%S').date()
            if last_used_date == date.today():
                await ctx.send("猴子今天已經工作過了，請明天再來！")
                return
    # else: 如果禁用冷卻，就跳過檢查繼續執行

    # 剩下的猴子操盤邏輯保持不變...
    if user_id in monkey_sell_state:
        await ctx.send("您已在等待輸入賣出價格的狀態，請先完成操作。")
        return

    # (參數驗證與權重調整邏輯與前版相同)
    # ...
    if user_id in monkey_sell_state:
        await ctx.send("您已在等待輸入賣出價格的狀態，請先完成操作。")
        return
    # ... (參數驗證與冷卻時間檢查，與前一版本相同)
    min_amount, max_amount = 5000, 100000
    if len(args) == 2:
        try:
            min_val, max_val = int(args[0]), int(args[1])
            if min_val < 0 or max_val < 0 or min_val >= max_val or (
                    max_val - min_val) < 1000:
                await ctx.send("❌ 金額範圍無效。")
                return
            min_amount, max_amount = min_val, max_val
        except ValueError:
            await ctx.send("❌ 金額參數格式錯誤。")
            return
    elif len(args) != 0:
        await ctx.send("❌ 參數數量錯誤！")
        return

    create_user_csv_if_not_exists(str(user_id))

    # ... (權重動態調整，與前一版本相同)
    df = get_user_data(str(user_id))
    inventory = df[df['類別'] == '庫存']
    summary_data = inventory.groupby('股票代碼').agg(股數=('股數',
                                                     'sum')).reset_index()
    has_inventory = not summary_data[summary_data['股數'] > 0].empty
    current_weights = MONKEY_WEIGHTS.copy()
    if not has_inventory:
        current_weights["sell"] = 0
        current_weights["hold"] = 0  # 如果沒有庫存，買入權重也設為 0 by za 20250909_2248
    chosen_action = random.choices(list(current_weights.keys()),
                                   weights=list(current_weights.values()),
                                   k=1)[0]

    await ctx.send(f"🍌 猴子操盤手開始工作了 (金額範圍: ${min_amount:,} ~ ${max_amount:,})..."
                   )

    # --- 買入/持有邏輯 (不變) ---
    if chosen_action == "buy":
        stock_code, stock_name = random.choice(list(stock_data.items()))
        stock_price = get_stock_price(stock_code)
        if stock_price <= 0:
            await ctx.send(f"猴子想買 **{stock_name}**，但查不到它的股價，只好放棄。")
            return
        amount = random.randrange(min_amount, max_amount + 1, 1000)
        shares = int(amount // stock_price)
        if shares == 0:
            await ctx.send(f"猴子想用約 {amount:,} 元買 **{stock_name}**，但錢不夠，只好放棄。")
            return
        buy_amount = round(shares * stock_price, 2)
        log_to_user_csv(str(user_id), "!monkey", "庫存", stock_code, stock_name,
                        shares, stock_price, buy_amount)
        log_to_user_csv(str(user_id), "!monkey", "操作", stock_code, stock_name,
                        shares, stock_price, buy_amount)
        await ctx.send(
            f"🐵 **買入！** 猴子幫您買了 **{shares}** 股的 **{stock_name}({stock_code})**！"
        )

    elif chosen_action == "hold":
        await ctx.send("🙉 **持有！** 猴子決定抱緊處理，今天不進行任何操作。")

    # --- 賣出邏輯 (進入狀態) ---
    elif chosen_action == "sell":
        stock_to_sell = summary_data[summary_data['股數'] > 0].sample(
            n=1).iloc[0]
        stock_code = stock_to_sell['股票代碼']
        shares_held = int(stock_to_sell['股數'])
        stock_name = get_stock_info(stock_code)[1]
        shares_to_sell = random.randint(1, shares_held)

        # 計算平均成本
        stock_inventory = inventory[inventory['股票代碼'] == stock_code]
        total_cost = stock_inventory['金額'].sum()
        average_cost_price = total_cost / shares_held

        # 儲存狀態
        monkey_sell_state[user_id] = {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "shares_to_sell": shares_to_sell,
            "average_cost": average_cost_price,
            "channel_id": ctx.channel.id  # 記錄頻道ID以便超時提醒
        }
        # 啟動非阻塞的超時任務
        #asyncio.create_task(handle_monkey_timeout(ctx.channel, user_id))

        await ctx.send(
            f"{ctx.author.mention}，猴子決定賣出 **{shares_to_sell}** 股的 **{stock_name}({stock_code})**，請在 120 秒內直接於頻道中輸入您要的賣出價格 (純數字)："
        )

    # --- 成功執行後，寫入冷卻紀錄 (重要) ---
    log_to_user_csv(str_user_id, "!monkey", "系統紀錄", "MONKEY_CD", "猴子冷卻紀錄", 0,
                    0, 0)


# --- 每月歸檔任務 ---
@tasks.loop(hours=1)  # 每小時檢查一次時間
async def monthly_archive():
    global is_archiving
    now = datetime.now()
    # 每月1號的 00:00 ~ 00:59 之間執行
    if now.day == 1 and now.hour == 0:
        is_archiving = True
        print(f"[{now}] 開始執行每月資料歸檔...")

        # 找出所有使用者 .csv 檔案 (排除上市股票.csv)
        csv_files = Path('.').glob('*.csv')
        user_csv_files = [f for f in csv_files if f.stem.isdigit()]

        for file_path in user_csv_files:
            user_id = file_path.stem
            print(f"  - 正在處理 {user_id}.csv ...")

            df = get_user_data(user_id, file_path=str(file_path))
            if df.empty:
                print(f"  - {user_id}.csv 是空的，跳過。")
                continue

            # 1. 計算庫存結餘
            inventory = df[df['類別'] == '庫存']
            summary = inventory.groupby(['股票代碼', '股票名稱'
                                         ]).agg(股數=('股數', 'sum'),
                                                總金額=('金額',
                                                     'sum')).reset_index()
            # 防呆：過濾掉總股數為 0 或負數的股票
            summary = summary[summary['股數'] > 0].copy()

            # 2. 建立使用者歸檔資料夾
            user_archive_dir = Path(user_id)
            user_archive_dir.mkdir(exist_ok=True)

            # 3. 移動舊檔案至歸檔資料夾
            last_month = now - timedelta(days=1)
            archive_filename = f"{last_month.strftime('%Y-%m')}_archive.csv"
            file_path.rename(user_archive_dir / archive_filename)

            # 4. 建立新檔案 (此函式會自動寫入標頭，確保一致性)
            create_user_csv_if_not_exists(user_id)

            # 5. 將結餘寫入新檔案
            if not summary.empty:
                # 確保計算平均股價時不會除以零
                summary['平均股價'] = summary.apply(
                    lambda row: row['總金額'] / row['股數']
                    if row['股數'] != 0 else 0,
                    axis=1)

                for _, row in summary.iterrows():
                    log_to_user_csv(user_id, "月結轉", "庫存", str(row['股票代碼']),
                                    str(row['股票名稱']), int(row['股數']),
                                    float(row['平均股價']), float(row['總金額']))
            print(f"  - {user_id}.csv 歸檔完成。")

        is_archiving = False
        print(f"[{datetime.now()}] 每月資料歸檔完成！")


# ---------- 啟動 Bot ----------
bot.run(TOKEN)
