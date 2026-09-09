import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from dateutil import relativedelta
from discord.ext import commands
from massive import RESTClient
from massive.exceptions import BadResponse
import matplotlib
matplotlib.use('Agg')   # We have to use Agg backend for Heroku
from matplotlib import pyplot as plt

# US market data from Massive is timestamped in UTC; the exchanges (and the old
# Alpha Vantage output this bot used to speak) work in US/Eastern.
EASTERN = ZoneInfo('America/New_York')

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='$', intents=intents)


def get_client():
    return RESTClient(api_key=os.environ['MASSIVE_API_KEY'], retries=5)


def bar_datetime(bar):
    """Convert a Massive aggregate bar's epoch-ms timestamp to an Eastern datetime."""
    return datetime.fromtimestamp(bar.timestamp / 1000, EASTERN)


def most_recent_grouped_daily(client, max_lookback=5):
    """Return (date_str, rows) for the latest trading day with grouped daily data.

    Massive's free tier has no same-day data, so this walks back from yesterday
    and also skips weekends/holidays (which come back as an empty result).
    """
    day = date.today()
    rows = []
    for _ in range(max_lookback + 1):
        day -= timedelta(days=1)
        if day.weekday() >= 5:
            continue
        rows = client.get_grouped_daily_aggs(day.isoformat())
        if rows:
            break
    return day.isoformat(), rows


def unwrap(result):
    """Massive's *_agg helpers return a single-item list; normalise to one object."""
    if isinstance(result, list):
        return result[0] if result else None
    return result


@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandInvokeError):
        print(error)
        await ctx.send(
            "There was an error retrieving the data for this request. "
            "Please make sure you're using valid arguments and try again"
        )


@bot.command()
async def price(ctx, *symbols: str):
    tickers = [symbol.upper() for symbol in symbols]
    if not tickers:
        await ctx.send("Usage: $price SYMBOL [SYMBOL ...]")
        return

    client = get_client()
    lines = []

    try:
        # Real-time snapshots - requires a paid Massive plan.
        snapshots = client.get_snapshot_all("stocks", tickers)
        by_ticker = {snapshot.ticker: snapshot for snapshot in snapshots}
        for ticker in tickers:
            snapshot = by_ticker.get(ticker)
            price = get_snapshot_price(snapshot) if snapshot is not None else None
            if price is None:
                lines.append("{}: no data".format(ticker))
                continue
            line = "{}: ${:,.2f}".format(ticker, float(price))
            change = getattr(snapshot, 'todays_change', None)
            change_pct = getattr(snapshot, 'todays_change_percent', None)
            if change is not None and change_pct is not None:
                line += " ({:+,.2f} / {:+.2f}%)".format(float(change), float(change_pct))
            lines.append(line)
    except BadResponse:
        # Free plan: fall back to the most recent end-of-day close. One call
        # covers every ticker the user asked for.
        day, rows = most_recent_grouped_daily(client)
        by_ticker = {row.ticker: row for row in rows}
        for ticker in tickers:
            row = by_ticker.get(ticker)
            if row is None:
                lines.append("{}: no close for {}".format(ticker, day))
                continue
            change = row.close - row.open
            change_pct = (change / row.open * 100) if row.open else 0.0
            lines.append("{}: ${:,.2f} ({:+,.2f} / {:+.2f}% on {})".format(
                ticker, float(row.close), change, change_pct, day))

    await ctx.send("\n".join(lines))


# Command to plot the latest available session's price data at a 5 min interval.
@bot.command()
async def plot_today(ctx, symbol: str):
    symbol = symbol.upper()
    client = get_client()
    from_str = (date.today() - timedelta(days=7)).isoformat()
    to_str = date.today().isoformat()

    bars = list(client.list_aggs(symbol, 5, 'minute', from_str, to_str, limit=50000))
    if len(bars) == 0:
        await ctx.send("Oops! It looks like I don't have any recent intraday data for {}.".format(symbol))
        return

    # On the free tier "today" is really the most recent session Massive has.
    latest_day = max(bar_datetime(bar).date() for bar in bars)
    session = [bar for bar in bars if bar_datetime(bar).date() == latest_day]

    times = [bar_datetime(bar).strftime('%H:%M') for bar in session]
    closes = [bar.close for bar in session]

    fig, ax = plt.subplots()
    ax.plot(times, closes)
    plt.title('Intraday Time Series for {} (5 min interval) on {}'.format(symbol, latest_day))

    xlabels = shrink_list(times, 21) if len(times) > 21 else times
    plt.xticks(xlabels, xlabels, fontsize=6, rotation=45, ha='right')

    # we want to hide every other label
    for label in ax.xaxis.get_ticklabels()[1::2]:
        label.set_visible(False)

    if os.path.exists('output.png'):
        print('Removing output.png')
        os.remove('output.png')

    plt.savefig('output.png')
    await ctx.send(file=discord.File('output.png'))
    plt.clf()


@bot.command()
async def plot_range(ctx, symbol: str, start: str, end: str):
    symbol = symbol.upper()
    start_datetime = datetime.strptime(start, '%m-%d-%Y')
    end_datetime = datetime.strptime(end, '%m-%d-%Y')
    filtered_data = []
    filtered_datetimes = []

    if start_datetime > end_datetime:
        await ctx.send("Error: Start date is after end date!")
        return

    rdelta = relativedelta.relativedelta(end_datetime, start_datetime)
    client = get_client()
    print('Years: ' + str(rdelta.years) + '\n'
          'Months: ' + str(rdelta.months) + '\n'
          'Days: ' + str(rdelta.days)
          )

    if rdelta.years >= 2:
        multiplier, timespan = 1, 'week'
        label_format = '%Y-%m-%d'
    elif rdelta.months >= 1 or rdelta.years >= 1:
        multiplier, timespan = 1, 'day'
        label_format = '%Y-%m-%d'
    elif rdelta.days >= 5:
        multiplier, timespan = 1, 'hour'
        label_format = '%Y-%m-%d %H:%M'
    else:
        multiplier, timespan = 30, 'minute'
        label_format = '%Y-%m-%d %H:%M'

    from_str = start_datetime.strftime('%Y-%m-%d')
    to_str = end_datetime.strftime('%Y-%m-%d')

    for agg in client.list_aggs(symbol, multiplier, timespan, from_str, to_str, limit=50000):
        filtered_datetimes.append(bar_datetime(agg).strftime(label_format))
        filtered_data.append(agg.close)

    if len(filtered_data) == 0:
        await ctx.send("Oops! It looks like I don't have enough data to plot {} in this range. "
                       " Try using a larger range or choosing a date range that is more recent.".format(symbol))
        return

    fig, ax = plt.subplots()
    ax.plot(filtered_datetimes, filtered_data)
    plt.title('Time Series for {} on {} - {}'.format(symbol,
                                                     datetime.strftime(start_datetime, '%m-%d-%Y'),
                                                     datetime.strftime(end_datetime, '%m-%d-%Y')))
    if len(filtered_datetimes) > 21:
        xlabels = shrink_list(filtered_datetimes, 21)
    else:
        xlabels = filtered_datetimes

    plt.xticks(xlabels, xlabels, fontsize=6, rotation=45, ha='right')

    # we want to hide every other label
    for label in ax.xaxis.get_ticklabels()[1::2]:
        label.set_visible(False)

    if os.path.exists('output.png'):
        print('Removing output.png')
        os.remove('output.png')

    plt.savefig('output.png')
    await ctx.send(file=discord.File('output.png'))
    plt.clf()


# Command to get current price of a cryptocurrency given a ticker symbol
@bot.command()
async def crypto_current_price(ctx, symbol: str, market: str):
    symbol = symbol.upper()
    market = market.upper()
    client = get_client()
    massive_ticker = "X:{}{}".format(symbol, market)
    output_header = "{} ({})".format(symbol, market)

    try:
        # Real-time snapshot - requires a paid Massive plan.
        snapshot = client.get_snapshot_ticker("crypto", massive_ticker)
        price = get_snapshot_price(snapshot)
        updated_ns = getattr(snapshot, 'updated', None)
        as_of = (datetime.fromtimestamp(updated_ns / 1e9, EASTERN)
                 if updated_ns else datetime.now(EASTERN))
    except BadResponse:
        # Free plan: fall back to the previous day's close.
        row = unwrap(client.get_previous_close_agg(massive_ticker))
        price = getattr(row, 'close', None) if row is not None else None
        as_of = bar_datetime(row) if row is not None and getattr(row, 'timestamp', None) else datetime.now(EASTERN)

    if price is None:
        output = "{}: no recent price data available".format(output_header)
    else:
        output = "{}: ${:,.2f} (as of {:%Y-%m-%d %H:%M %Z})".format(output_header, float(price), as_of)
    print(output)
    await ctx.send(output)


def shrink_list(list_to_shrink, target_len):
    shrunken_list = []
    n = int(len(list_to_shrink)/target_len)

    for x in list_to_shrink[0::n]:
        shrunken_list.append(x)

    return shrunken_list


def get_snapshot_price(snapshot):
    """Pull the most relevant price out of a Massive TickerSnapshot."""
    if snapshot is None:
        return None

    last_trade = getattr(snapshot, 'last_trade', None)
    if last_trade is not None and getattr(last_trade, 'price', None):
        return last_trade.price

    day = getattr(snapshot, 'day', None)
    if day is not None and getattr(day, 'close', None):
        return day.close

    prev_day = getattr(snapshot, 'prev_day', None)
    if prev_day is not None and getattr(prev_day, 'close', None):
        return prev_day.close

    return None


discord_token = os.environ['DISCORD_TOKEN']
bot.run(discord_token)
