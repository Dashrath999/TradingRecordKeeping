from django.shortcuts import render, HttpResponse, redirect
from .forms import NewTradeForm, NewAccountForm, NewTradeStepForm
from .models import Accounts, Trades, TradeSteps, LedgerNotes
from decimal import Decimal
import os
from django.conf import settings
import mplfinance as mpf
from pathlib import Path
from django.core.files import File
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from django.db.models import Sum, Avg
from django.http import JsonResponse
from calendar import monthrange
from twelvedata import TDClient



#ALL ORIGINAL TODOS DONE (June 2026):
# edit/delete for trades and trade steps (replay_trade engine: revert cash -> reset to entry -> re-apply steps)
# stop loss recalculated after scale in/out (current_stop_loss field, keeps original € risk on current size)
# ledger notes save via fetch, no redirect
# equity curve seeded with real pre-period balance (get_starting_balance), cumulative net P&L, works for 'All' accounts
# every generated plot kept (timestamped), gallery in trade detail
#
#FIXED EARLIER (June 2026):
# yfinance removed, Twelve Data only, API key now read from env var TWELVEDATA_API_KEY
# short positions P&L was inverted (calculate_current_pl / calculate_realized_pl / pl_if_hit)
# avg cost: commission removed from trade_total_cost; realized_pl used wrong denominator
# commission now deducted from account balance at close (pl stays gross, ledger nets it)
# profit factor used signed gross_loss -> abs(); win rate shows N/A with 0 closed trades
# screenshots: timeframe mapped to TD intervals, intraday markers (nearest candle), failures no longer break trade creation
# elif 'Daily' always-true condition

def dashboard(request):
    new_trade_form = NewTradeForm()
    new_account_form = NewAccountForm()

    accounts = []
    accounts_db = Accounts.objects.all()
    for a in accounts_db:
        accounts.append(a.name)

    all_trades = Trades.objects.order_by('date_open').all()

    return render(request, "record/dashboard.html", {'new_trade_form': new_trade_form, 'new_account_form': new_account_form, 'accounts': accounts, 'all_trades': all_trades})


def loaddata(request):
    try:
        time_frame = request.GET['time_frame']
        date = request.GET['date']
        account_name = request.GET['account_name']
        account = Accounts.objects.filter(name=account_name).first()
    except:
        return HttpResponse(400)

    #Get trades for the selected time_frame    
    if time_frame == 'All':
        time_frame_trades = Trades.objects.order_by('date_open').all() if account_name == 'All' else Trades.objects.filter(account_id=account).order_by('date_open').all()
    elif time_frame == 'Date Range':
        start_date, end_date = date.split(',')
        start_date, end_date = datetime.strptime(start_date,'%d.%m.%Y'), datetime.strptime(end_date,' %d.%m.%Y')

        time_frame_trades = Trades.objects.filter(date_open__gte=start_date, date_open__lte=end_date).order_by('date_open').all() if account_name == 'All' else Trades.objects.filter(account_id=account).filter(date_open__gte=start_date, date_open__lte=end_date).order_by('date_open').all()
    elif time_frame == 'Yearly':
        year = date.split('.')[-1]

        time_frame_trades = Trades.objects.filter(date_open__year=year).order_by('date_open').all() if account_name == 'All' else Trades.objects.filter(account_id=account).filter(date_open__year=year).order_by('date_open').all()
    elif time_frame == 'Monthly':
        _, month, year = date.split('.')

        time_frame_trades = Trades.objects.filter(date_open__year=year, date_open__month=month).order_by('date_open').all() if account_name == 'All' else Trades.objects.filter(account_id=account).filter(date_open__year=year, date_open__month=month).order_by('date_open').all()
    elif time_frame == 'Daily':
        day, month, year = date.split('.')

        time_frame_trades = Trades.objects.filter(date_open__year=year, date_open__month=month, date_open__day=day).order_by('date_open').all() if account_name == 'All' else Trades.objects.filter(account_id=account).filter(date_open__year=year, date_open__month=month, date_open__day=day).order_by('date_open').all()
    else:
        return HttpResponse(400)

    json_resp = {}
    #calculate total_pl and closed trades pl
    json_resp['total_pl'] = s_round(time_frame_trades.aggregate(total=Sum('pl'))['total'], 2) if time_frame_trades.aggregate(total=Sum('pl'))['total'] != None else 'N/A'
    json_resp['closed_trade_pl'] = s_round(time_frame_trades.filter(status='Closed').aggregate(total=Sum('pl'))['total'], 2) if time_frame_trades.filter(status='Closed').aggregate(total=Sum('pl'))['total'] != None else 'N/A'

    #calculate win rate
    time_frame_closed_trades = time_frame_trades.filter(status='Closed')
    total_nb_trades_closed = len(time_frame_closed_trades)
    total_nb_trades_win = len(time_frame_closed_trades.filter(trade_is_won=True))

    json_resp['won_trade_percent'] = s_round((total_nb_trades_win / total_nb_trades_closed) * 100, 2) if total_nb_trades_closed > 0 else 'N/A'

    #calculate profit factor
    gross_profit = time_frame_closed_trades.filter(trade_is_won=True).aggregate(total=Sum('pl'))['total']
    gross_loss = time_frame_closed_trades.filter(trade_is_won=False).aggregate(total=Sum('pl'))['total']

    if gross_loss == None or gross_profit == None:
        json_resp['profit_factor'] = '∞'
    else:
        #gross_loss is negative -> use abs() so the ratio is positive
        json_resp['profit_factor'] = s_round(gross_profit / abs(gross_loss), 2) if gross_loss != 0 else '∞'


    #get largest and average winning and loosing trade
    max_trade = time_frame_closed_trades.order_by('-pl').first()
    json_resp['max_trade'] = (s_round(max_trade.pl, 2), s_round(max_trade.id, 2)) if max_trade != None and max_trade.pl > 0 else 'N/A'

    min_trade = time_frame_closed_trades.order_by('pl').first()
    json_resp['min_trade'] = (s_round(min_trade.pl, 2), s_round(min_trade.id, 2)) if min_trade != None and min_trade.pl < 0 else 'N/A'

    json_resp['avg_win'] = s_round(time_frame_closed_trades.filter(trade_is_won=True).aggregate(avg=Avg('pl'))['avg'], 2) if time_frame_closed_trades.filter(trade_is_won=True).aggregate(avg=Avg('pl'))['avg'] != None else 'N/A'
    json_resp['avg_lost'] = s_round(time_frame_closed_trades.filter(trade_is_won=False).aggregate(avg=Avg('pl'))['avg'], 2) if time_frame_closed_trades.filter(trade_is_won=False).aggregate(avg=Avg('pl'))['avg'] != None else 'N/A'

    #get equity curve (account is None when 'All' accounts is selected)
    json_resp['equity_curve_labels'], json_resp['equity_curve_data'] = get_equity_curve_labels_and_data(time_frame, date, account)

    #get adequate ledger
    json_resp['ledger_header'], json_resp['ledger_rows']  = get_ledger_data(time_frame, time_frame_trades, date)
    
    #get ledger note if any
    account_name = 'All' if account == None else account.name
    json_resp['ledger_note'] = LedgerNotes.objects.filter(date=date, ledger_timeframe=time_frame, account_name=account_name).first().notes if len(LedgerNotes.objects.filter(date=date, ledger_timeframe=time_frame, account_name=account_name)) > 0 else ''

    #get time_frame_trades table
    trade_table = []
    for t in time_frame_trades:
        trade_table.append([t.id, t.status, t.date_open.strftime("%Y-%m-%d %H:%M"), t.date_closed.strftime("%Y-%m-%d %H:%M") if t.date_closed else '', t.symbol, t.position, t.timeframe, t.trade_size, t.trade_total_cost, t.commission_fee, t.pl, t.account_id.name])

    json_resp['trade_table'] = trade_table

    return JsonResponse(json_resp)

def new_ledger_note(request):
    if request.method == 'POST':
        try:
            time_frame = request.POST['time_frame']
            date = None if request.POST['date'] == 'null' else request.POST['date']
            account = request.POST['account']

            if len(LedgerNotes.objects.filter(date=date, ledger_timeframe=time_frame, account_name=account)) > 0:
                LedgerNotes.objects.filter(date=date, ledger_timeframe=time_frame, account_name=account).update(notes=request.POST['note'])
            else:
                LedgerNotes(notes=request.POST['note'], date=date, ledger_timeframe=time_frame, account_name=account).save()

            #no redirect: the dashboard JS submits via fetch and shows inline feedback
            return JsonResponse({'status': 'ok'})
        
        except Exception as e:
            print(request.POST, e)
            return HttpResponse(400)


def get_ledger_data(time_frame, time_frame_trades, date):
    ledger_rows = []

    if time_frame == 'All' or time_frame == 'Date Range':
        ledger_header = 'All' if time_frame == 'All' else f'Date Range - {date}'
        ledger_period_trades = time_frame_trades

        nb_trades = len(ledger_period_trades)
        nb_w_trades = len(ledger_period_trades.filter(status='Closed').filter(trade_is_won=True))
        nb_l_trades = len(ledger_period_trades.filter(status='Closed').filter(trade_is_won=False))
        gross_pl = s_round(ledger_period_trades.aggregate(total=Sum('pl'))['total'])
        comissions = s_round(ledger_period_trades.aggregate(total=Sum('commission_fee'))['total'])
        net_pl = s_round(ledger_period_trades.aggregate(total=Sum('pl'))['total']) - s_round(ledger_period_trades.aggregate(total=Sum('commission_fee'))['total'])
        running_pl = (s_round(ledger_period_trades.aggregate(total=Sum('pl'))['total']) - s_round(ledger_period_trades.aggregate(total=Sum('commission_fee'))['total']))

        ledger_rows.append(['All Trades' if time_frame == 'All' else f'Date Range - {date}', nb_trades, nb_w_trades, nb_l_trades, gross_pl, comissions, net_pl, running_pl])

    elif time_frame == 'Yearly':
        ledger_header = 'Months'
        ledger_first_col = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
        
        day, month, year = date.split('.')
        previous_running_pl = 0
        for i, month in enumerate(ledger_first_col):
            ledger_period_trades = time_frame_trades.filter(date_open__year=year, date_open__month=i+1)

            nb_trades = len(ledger_period_trades)
            nb_w_trades = len(ledger_period_trades.filter(status='Closed').filter(trade_is_won=True))
            nb_l_trades = len(ledger_period_trades.filter(status='Closed').filter(trade_is_won=False))
            gross_pl = s_round(ledger_period_trades.aggregate(total=Sum('pl'))['total'])
            comissions = s_round(ledger_period_trades.aggregate(total=Sum('commission_fee'))['total'])
            net_pl = s_round(ledger_period_trades.aggregate(total=Sum('pl'))['total']) - s_round(ledger_period_trades.aggregate(total=Sum('commission_fee'))['total'])
            running_pl = previous_running_pl + (s_round(ledger_period_trades.aggregate(total=Sum('pl'))['total']) - s_round(ledger_period_trades.aggregate(total=Sum('commission_fee'))['total']))

            ledger_rows.append([month, nb_trades, nb_w_trades, nb_l_trades, gross_pl, comissions, net_pl, running_pl])
            previous_running_pl = previous_running_pl + (s_round(ledger_period_trades.aggregate(total=Sum('pl'))['total']) - s_round(ledger_period_trades.aggregate(total=Sum('commission_fee'))['total']))


    elif time_frame == 'Monthly':
        ledger_header = 'Days'

        day, month, year = date.split('.')
        month_range = monthrange(int(year), int(month))[1]
        ledger_first_col = list(range(1, month_range + 1))

        previous_running_pl = 0
        for i in ledger_first_col:
            ledger_period_trades = time_frame_trades.filter(date_open__year=year, date_open__month=month, date_open__day=i)

            nb_trades = len(ledger_period_trades)
            nb_w_trades = len(ledger_period_trades.filter(status='Closed').filter(trade_is_won=True))
            nb_l_trades = len(ledger_period_trades.filter(status='Closed').filter(trade_is_won=False))
            gross_pl = s_round(ledger_period_trades.aggregate(total=Sum('pl'))['total'])
            comissions = s_round(ledger_period_trades.aggregate(total=Sum('commission_fee'))['total'])
            net_pl = s_round(ledger_period_trades.aggregate(total=Sum('pl'))['total']) - s_round(ledger_period_trades.aggregate(total=Sum('commission_fee'))['total'])
            running_pl = previous_running_pl + (s_round(ledger_period_trades.aggregate(total=Sum('pl'))['total']) - s_round(ledger_period_trades.aggregate(total=Sum('commission_fee'))['total']))

            ledger_rows.append([i, nb_trades, nb_w_trades, nb_l_trades, gross_pl, comissions, net_pl, running_pl])
            previous_running_pl = previous_running_pl + (s_round(ledger_period_trades.aggregate(total=Sum('pl'))['total']) - s_round(ledger_period_trades.aggregate(total=Sum('commission_fee'))['total']))


    elif time_frame == 'Daily':
        ledger_header = 'Hours'
        ledger_first_col = list(range(24))

        day, month, year = date.split('.')
        previous_running_pl = 0
        for i in ledger_first_col:
            ledger_period_trades = time_frame_trades.filter(date_open__year=year, date_open__month=month, date_open__day=day, date_open__hour=i)

            nb_trades = len(ledger_period_trades)
            nb_w_trades = len(ledger_period_trades.filter(status='Closed').filter(trade_is_won=True))
            nb_l_trades = len(ledger_period_trades.filter(status='Closed').filter(trade_is_won=False))
            gross_pl = s_round(ledger_period_trades.aggregate(total=Sum('pl'))['total'])
            comissions = s_round(ledger_period_trades.aggregate(total=Sum('commission_fee'))['total'])
            net_pl = s_round(ledger_period_trades.aggregate(total=Sum('pl'))['total']) - s_round(ledger_period_trades.aggregate(total=Sum('commission_fee'))['total'])
            running_pl = previous_running_pl + (s_round(ledger_period_trades.aggregate(total=Sum('pl'))['total']) - s_round(ledger_period_trades.aggregate(total=Sum('commission_fee'))['total']))

            ledger_rows.append([i, nb_trades, nb_w_trades, nb_l_trades, gross_pl, comissions, net_pl, running_pl])
            previous_running_pl = previous_running_pl + (s_round(ledger_period_trades.aggregate(total=Sum('pl'))['total']) - s_round(ledger_period_trades.aggregate(total=Sum('commission_fee'))['total']))

    return ledger_header, ledger_rows


def get_starting_balance(account, before_dt):
    """Account balance (or sum of all accounts) just before before_dt:
    initial balance(s) + net P&L of every trade closed before that moment.
    before_dt=None -> just the initial balance(s) (curve covers everything)."""
    if account is None:
        base = Accounts.objects.aggregate(total=Sum('initial_balance'))['total'] or Decimal('0')
        prior = Trades.objects.filter(status='Closed')
    else:
        base = account.initial_balance
        prior = Trades.objects.filter(status='Closed', account_id=account)

    if before_dt is None:
        return base

    prior = prior.filter(date_closed__lt=before_dt)
    pl = prior.aggregate(total=Sum('pl'))['total'] or Decimal('0')
    fees = prior.aggregate(total=Sum('commission_fee'))['total'] or Decimal('0')
    return base + pl - fees


def get_equity_curve_labels_and_data(time_frame, date, account):
    """Equity curve seeded with the REAL pre-period balance (TODO fixed: no
    longer starts at 0). Computed cumulatively from net P&L (pl - commission)
    of trades selected by date_CLOSED, so it also works for account='All'."""
    closed = Trades.objects.filter(status='Closed') if account is None else Trades.objects.filter(status='Closed', account_id=account)

    def net(t):
        return Decimal(t.pl) - Decimal(t.commission_fee)

    if time_frame == 'All' or time_frame == 'Date Range':
        if time_frame == 'Date Range':
            start_date, end_date = date.split(',')
            start_date, end_date = datetime.strptime(start_date, '%d.%m.%Y'), datetime.strptime(end_date, ' %d.%m.%Y')
            closed = closed.filter(date_closed__gte=start_date, date_closed__lte=end_date)
            balance = get_starting_balance(account, start_date)
        else:
            balance = get_starting_balance(account, None)

        labels = ['Start']
        data = [balance]
        for t in closed.order_by('date_closed'):
            balance += net(t)
            labels.append(t.date_closed)
            data.append(balance)

    elif time_frame == 'Yearly':
        day, month, year = date.split('.')
        labels = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
        balance = get_starting_balance(account, datetime(int(year), 1, 1))
        data = []
        for i in range(1, 13):
            for t in closed.filter(date_closed__year=year, date_closed__month=i):
                balance += net(t)
            data.append(balance)

    elif time_frame == 'Monthly':
        day, month, year = date.split('.')
        month_range = monthrange(int(year), int(month))[1]
        labels = list(range(1, month_range + 1))
        balance = get_starting_balance(account, datetime(int(year), int(month), 1))
        data = []
        for i in range(1, month_range + 1):
            for t in closed.filter(date_closed__year=year, date_closed__month=month, date_closed__day=i):
                balance += net(t)
            data.append(balance)

    elif time_frame == 'Daily':
        day, month, year = date.split('.')
        labels = list(range(24))
        balance = get_starting_balance(account, datetime(int(year), int(month), int(day)))
        data = []
        for i in range(24):
            for t in closed.filter(date_closed__year=year, date_closed__month=month, date_closed__day=day, date_closed__hour=i):
                balance += net(t)
            data.append(balance)

    return labels, data


def new_trade(request):
    if request.method == 'POST':
        f = NewTradeForm(request.POST)
        if f.is_valid():
            f = f.cleaned_data

            #GET TRADE_SIZE AND TRADE_TOTAL_COST
            trade_size, trade_total_cost = calculate_trade_size_and_cost(f['account_id'].current_balance, f['risk'], f['entry_price'], f['initial_stop_loss'], f['commission_fee'])

            #CREATE NEW_TRADE
            new_trade = Trades(date_open=f['date_open'], account_id=f['account_id'], position=f['position'], timeframe=f['timeframe'], symbol=f['symbol'], entry_price=f['entry_price'], trade_size=trade_size, total_trade_size=trade_size, trade_total_cost=trade_total_cost, initial_stop_loss=f['initial_stop_loss'], current_stop_loss=f['initial_stop_loss'], initial_tp=f['initial_tp'], commission_fee=f['commission_fee'], risk=f['risk'], notes='')
            new_trade.save()

            #CREATE ENTRY TRADE STEP (pl_if_hit is direction-aware)
            if new_trade.initial_tp:
                if new_trade.position == 'Short':
                    pl_if_hit = (Decimal(new_trade.entry_price) - Decimal(new_trade.initial_tp)) * Decimal(new_trade.trade_size)
                else:
                    pl_if_hit = (Decimal(new_trade.initial_tp) - Decimal(new_trade.entry_price)) * Decimal(new_trade.trade_size)
            else:
                pl_if_hit = None
            TradeSteps(trade_id=new_trade, datetime=f['date_open'], type="Entry", current_market_price=f['entry_price'], current_trade_size=trade_size, current_pl=0, pl_if_hit=pl_if_hit).save()

            #CREATE INITIAL SCREENSHOT WITH ENTRY, SL AND TP? MARKERS
            create_screenshot(new_trade)

            return redirect('record-dashboard')
        else:
            return HttpResponse(400)


#Model timeframe values -> Twelve Data interval strings
TWELVEDATA_INTERVALS = {
    "1month": "1month", "1week": "1week", "1day": "1day",
    "4h": "4h", "2h": "2h", "1h": "1h",
    "30m": "30min", "15m": "15min", "5m": "5min",
}


def nearest_candle_index(data, dt):
    """Return the index label of the candle closest to dt (works for intraday too)."""
    idx = data.index.get_indexer([pd.Timestamp(dt).tz_localize(None)], method='nearest')[0]
    return data.index[idx]


def create_screenshot(trade_info):
    #Screenshot generation must NEVER break trade creation/updates:
    #any failure is logged and the trade simply has no chart.
    try:
        # api_key = os.environ.get('TWELVEDATA_API_KEY')
        api_key = "ec8e9db4055444fda2f7d8b26e619fc2"
        if not api_key:
            print('create_screenshot skipped: TWELVEDATA_API_KEY not set')
            return

        td = TDClient(apikey=api_key)
        interval = TWELVEDATA_INTERVALS.get(trade_info.timeframe, '1day')
        data = td.time_series(symbol=trade_info.symbol, interval=interval, outputsize=50)
        data = data.as_pandas()
        data = data[::-1]
        ap = []

        #make entry signal addplot (nearest candle, not exact date string)
        entry_series = pd.Series(index=data.index, data=np.nan)
        entry_series[nearest_candle_index(data, trade_info.date_open)] = data.loc[nearest_candle_index(data, trade_info.date_open), "close"]
        ap.append(mpf.make_addplot(entry_series, type='scatter', markersize=100, marker='o', color='g'))

        #create sl and tp horizontal line
        hlines = {}
        hlines['hlines'] = [trade_info.initial_stop_loss, trade_info.initial_tp] if trade_info.initial_tp else [trade_info.initial_stop_loss]
        hlines['colors'] = ['r', 'g'] if trade_info.initial_tp else ['r']
        hlines['linestyle'] = '-.'

        #ITERATE THROUGH RELEVANT TRADE_STEPS TO MARK THEM ON THE PLOT
        trade_steps = TradeSteps.objects.filter(trade_id=trade_info.id).order_by('datetime').all()

        step_markers = {
            'Scale In': ('^', 'c'),
            'Scale Out': ('v', 'c'),
            'Stopped Out': ('x', 'r'),
            'Take Profit': ('x', 'g'),
        }

        trailling_stop_points = []
        for t in trade_steps:
            if t.type == 'Trailing Stop':
                trailing_stop_price = t.target_market_price
                trailing_stop_start = nearest_candle_index(data, t.datetime)
                trailling_stop_points.append([(trailing_stop_start, trailing_stop_price), (data.index[-1], trailing_stop_price)])

            elif t.type in step_markers:
                marker, color = step_markers[t.type]
                series = pd.Series(index=data.index, data=np.nan)
                candle = nearest_candle_index(data, t.datetime)
                series[candle] = data.loc[candle, "close"]
                ap.append(mpf.make_addplot(series, type='scatter', markersize=100, marker=marker, color=color))

        #save plot to filesystem - every generated plot is KEPT (timestamped
        #filename); the trade's screenshot field always points to the latest
        media_root = Path(settings.MEDIA_ROOT)
        media_root.mkdir(exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = media_root / f'trade_{trade_info.id}_{stamp}.png'
        plot_kwargs = dict(type='candle', style='yahoo', volume=True if "volume" in data.columns else False, savefig=str(path.with_suffix('')), addplot=ap, hlines=hlines)
        if trailling_stop_points:
            plot_kwargs['alines'] = dict(alines=trailling_stop_points, colors=['c'])
        mpf.plot(data, **plot_kwargs)
        with path.open(mode="rb") as file:
            Trades.objects.filter(id=trade_info.id).update(screenshot=File(file, name=path.name))

    except Exception as e:
        print(f'create_screenshot failed for trade {trade_info.id}: {e}') 



def calculate_trade_size_and_cost(account_balance, risk, entry_price, stop_loss, commision):
    risk_amount = Decimal(account_balance * (risk / 100))

    stop_loss_per_unit = Decimal(abs(entry_price - stop_loss))

    trade_size = Decimal(risk_amount / stop_loss_per_unit)
    #trade_total_cost = pure position cost, EXCLUDING commission.
    #Commission is tracked in commission_fee and deducted from the account at close;
    #including it here skewed the average cost and every P&L derived from it.
    trade_total_cost = trade_size * Decimal(entry_price)

    return trade_size, trade_total_cost


def new_account(request):
    if request.method == 'POST':
        f = NewAccountForm(request.POST)
        if f.is_valid():
            f = f.cleaned_data
            new_account = Accounts(name=f['name'], initial_balance=f['initial_balance'], current_balance=f['initial_balance'])
            new_account.save()

            return redirect('record-dashboard')
        else:
            return HttpResponse(400)


def trade_detail(request):
    try:
        trade_id = request.GET['trade_id']
    except Exception as e:
        print(f'error {e}')
        return HttpResponse(500)
    
    new_trade_step_form = NewTradeStepForm()
    trade_info = Trades.objects.filter(id=trade_id).all()
    edit_trade_form = NewTradeForm(instance=trade_info[0])
    trade_note = trade_info[0].notes
    trade_steps = TradeSteps.objects.filter(trade_id=trade_id).order_by('datetime').all()

    #all generated plots for this trade (timestamped) + legacy single file, newest first
    media_root = Path(settings.MEDIA_ROOT)
    shots = sorted(media_root.glob(f'trade_{trade_id}_*.png')) + sorted(media_root.glob(f'trade_{trade_id}.png'))
    screenshots = [settings.MEDIA_URL + s.name for s in reversed(shots)]

    return render(request, "record/trade_detail.html", {'trade_info': trade_info, 'trade_steps': trade_steps, 'new_trade_step_form': new_trade_step_form, 'edit_trade_form': edit_trade_form, 'trade_id': trade_id, 'trade_note': trade_note, 'screenshots': screenshots})


def new_trade_step(request):
    if request.method == 'POST':
        f = NewTradeStepForm(request.POST)
        if f.is_valid() and request.POST['trade_id']:
            f = f.cleaned_data
            last_trade_step_data = TradeSteps.objects.filter(trade_id=request.POST['trade_id']).latest('datetime')
            trade_info = Trades.objects.filter(id=request.POST['trade_id']).first()
            entry_step = TradeSteps.objects.filter(trade_id=request.POST['trade_id'], type='Entry').first()
            entry_size = entry_step.current_trade_size if entry_step else trade_info.total_trade_size

            if f['type'] == 'Trailing Stop':
                #CREATE NEW TRADE STEP
                current_pl = calculate_current_pl(trade_info, last_trade_step_data.current_trade_size, f['current_market_price'])
                pl_if_hit = calculate_current_pl(trade_info, last_trade_step_data.current_trade_size, f['target_market_price'])
                TradeSteps(trade_id=trade_info, target_market_price=f['target_market_price'], trade_size_amount=f['trade_size_amount'] ,datetime=f['datetime'], type=f['type'], current_market_price=f['current_market_price'], current_trade_size=last_trade_step_data.current_trade_size, current_pl=current_pl, trade_size_if_hit=0, pl_if_hit=pl_if_hit).save()

                #CREATE SCREENSHOT
                create_screenshot(trade_info)

                #UPDATE TRADE_INFO (the trailing stop becomes the current stop)
                trade_info.pl = current_pl
                trade_info.current_stop_loss = f['target_market_price']
                trade_info.save()

            elif f['type'] == 'Scale In':
                #UPDATE TRADE_INFO
                trade_info.total_trade_size += f['trade_size_amount']
                trade_info.trade_size += f['trade_size_amount']
                trade_info.trade_total_cost += Decimal(f['current_market_price']) * Decimal(f['trade_size_amount'])
                current_pl = calculate_current_pl(trade_info, trade_info.trade_size, f['current_market_price'])
                trade_info.pl = current_pl
                trade_info.current_stop_loss = recalculate_stop_loss(trade_info, entry_size)

                trade_info.save()

                #CREATE NEW TRADE STEP
                TradeSteps(trade_id=trade_info, trade_size_amount=f['trade_size_amount'] ,datetime=f['datetime'], type=f['type'], current_market_price=f['current_market_price'], current_trade_size=trade_info.trade_size, current_pl=current_pl).save()

                #CREATE SCREENSHOT
                create_screenshot(trade_info)

            elif f['type'] == 'Scale Out':
                #GET REALIZED PL
                realized_pl = calculate_realized_pl(trade_info, f['current_market_price'], f['trade_size_amount'])
                trade_info.realized_pl += Decimal(realized_pl)

                #UPDATE TRADE INFO
                trade_info.trade_size -= f['trade_size_amount']
                current_pl = calculate_current_pl(trade_info, trade_info.trade_size, f['current_market_price'])
                trade_info.pl = current_pl
                trade_info.current_stop_loss = recalculate_stop_loss(trade_info, entry_size)

                trade_info.save()
                
                #CREATE NEW TRADE STEP
                TradeSteps(trade_id=trade_info, trade_size_amount=f['trade_size_amount'] ,datetime=f['datetime'], type=f['type'], current_market_price=f['current_market_price'], current_trade_size=trade_info.trade_size, current_pl=current_pl).save()

                #CREATE SCREENSHOT
                create_screenshot(trade_info)

            elif f['type'] == 'Stopped Out' or f['type'] == 'Take Profit':
                #UPDATE TRADE_INFO
                #pl stays GROSS of commission (the ledger computes net_pl = pl - commission);
                #the account balance, however, must reflect real cash -> deduct the fee there.
                current_pl = calculate_current_pl(trade_info, last_trade_step_data.current_trade_size, f['current_market_price'])
                net_cash_impact = Decimal(current_pl) - Decimal(trade_info.commission_fee)
                trade_info.pl = current_pl
                trade_info.date_closed = f['datetime']
                trade_info.status = 'Closed'
                trade_info.exit_price = f['current_market_price']
                trade_info.trade_is_won = True if current_pl > 0 else False
                trade_info.account_balance_post_trade = trade_info.account_id.current_balance + net_cash_impact

                trade_info.save()

                #UPDATE ACCOUNT DATA
                trade_info.account_id.current_balance += net_cash_impact
                trade_info.account_id.save()

                #CREATE NEW TRADE STEP
                TradeSteps(trade_id=trade_info, trade_size_amount=f['trade_size_amount'] ,datetime=f['datetime'], type=f['type'], current_market_price=f['current_market_price'], current_trade_size=0, current_pl=current_pl).save()

                #CREATE SCREENSHOT
                create_screenshot(trade_info)

            return redirect(f'/trade_detail?trade_id={request.POST["trade_id"]}')
        else:
            return HttpResponse(400)


def edit_trade(request):
    """Edit a trade's defining fields. Position size and cost are recomputed
    (risk % of the account's CURRENT balance, after reverting this trade's own
    cash impact), the Entry step is rebuilt, then every step is replayed."""
    if request.method == 'POST':
        trade_info = Trades.objects.filter(id=request.POST.get('trade_id')).first()
        f = NewTradeForm(request.POST)
        if trade_info and f.is_valid():
            f = f.cleaned_data

            #revert cash impact first so sizing uses a clean balance
            revert_closed_trade_cash(trade_info)

            trade_info.date_open = f['date_open']
            trade_info.account_id = f['account_id']
            trade_info.position = f['position']
            trade_info.timeframe = f['timeframe']
            trade_info.symbol = f['symbol']
            trade_info.entry_price = f['entry_price']
            trade_info.initial_stop_loss = f['initial_stop_loss']
            trade_info.initial_tp = f['initial_tp']
            trade_info.commission_fee = f['commission_fee']
            trade_info.risk = f['risk']

            trade_size, trade_total_cost = calculate_trade_size_and_cost(trade_info.account_id.current_balance, f['risk'], f['entry_price'], f['initial_stop_loss'], f['commission_fee'])
            trade_info.trade_size = trade_size
            trade_info.total_trade_size = trade_size
            trade_info.trade_total_cost = trade_total_cost
            trade_info.save()

            #rebuild the entry step with the new size, then replay everything
            entry_step = TradeSteps.objects.filter(trade_id=trade_info.id, type='Entry').first()
            if entry_step:
                entry_step.current_trade_size = trade_size
                entry_step.save()

            replay_trade(trade_info)
            create_screenshot(trade_info)

            return redirect(f'/trade_detail?trade_id={trade_info.id}')
        return HttpResponse(400)


def delete_trade(request):
    """Delete a trade (steps cascade). A closed trade's cash impact is
    reverted from its account first; screenshot files are removed."""
    if request.method == 'POST':
        trade_info = Trades.objects.filter(id=request.POST.get('trade_id')).first()
        if trade_info is None:
            return JsonResponse({'status': 'error', 'message': 'trade not found'}, status=404)

        revert_closed_trade_cash(trade_info)

        media_root = Path(settings.MEDIA_ROOT)
        for shot in list(media_root.glob(f'trade_{trade_info.id}_*.png')) + list(media_root.glob(f'trade_{trade_info.id}.png')):
            try:
                shot.unlink()
            except OSError:
                pass

        trade_info.delete()
        return JsonResponse({'status': 'ok'})
    return HttpResponse(400)


def edit_trade_step(request):
    """Edit a step (datetime, prices, size amount, type - Entry excluded),
    then replay the whole trade so every derived value stays consistent."""
    if request.method == 'POST':
        step = TradeSteps.objects.filter(id=request.POST.get('step_id')).first()
        if step is None or step.type == 'Entry':
            return HttpResponse(400)

        f = NewTradeStepForm(request.POST)
        if f.is_valid():
            f = f.cleaned_data
            step.datetime = f['datetime']
            step.type = f['type']
            step.current_market_price = f['current_market_price']
            step.target_market_price = f['target_market_price']
            step.trade_size_amount = f['trade_size_amount']
            step.save()

            trade_info = step.trade_id
            replay_trade(trade_info)
            create_screenshot(trade_info)

            return redirect(f'/trade_detail?trade_id={trade_info.id}')
        return HttpResponse(400)


def delete_trade_step(request):
    """Delete a step (Entry excluded - delete the trade instead), then replay."""
    if request.method == 'POST':
        step = TradeSteps.objects.filter(id=request.POST.get('step_id')).first()
        if step is None:
            return JsonResponse({'status': 'error', 'message': 'step not found'}, status=404)
        if step.type == 'Entry':
            return JsonResponse({'status': 'error', 'message': "The Entry step can't be deleted - delete the trade instead."}, status=400)

        trade_info = step.trade_id
        step.delete()
        replay_trade(trade_info)
        create_screenshot(trade_info)

        return JsonResponse({'status': 'ok'})
    return HttpResponse(400)

def calculate_avg_cost(trade_info):
    #trade_total_cost is the cumulative cost of all entries (excl. commission),
    #total_trade_size the cumulative size of all entries -> true average entry price
    return Decimal(trade_info.trade_total_cost) / Decimal(trade_info.total_trade_size)


def calculate_current_pl(trade_info, current_trade_size, current_market_price):
    avg_cost = calculate_avg_cost(trade_info)

    #CALCULATE UNREALIZED PL (direction-aware: a short profits when price drops)
    if trade_info.position == 'Short':
        unrealized_pl = (avg_cost - Decimal(current_market_price)) * Decimal(current_trade_size)
    else:
        unrealized_pl = (Decimal(current_market_price) - avg_cost) * Decimal(current_trade_size)

    return unrealized_pl + trade_info.realized_pl


def calculate_realized_pl(trade_info, current_market_price, sold_trade_size):
    avg_cost = calculate_avg_cost(trade_info)

    if trade_info.position == 'Short':
        return (avg_cost - Decimal(current_market_price)) * Decimal(sold_trade_size)
    return (Decimal(current_market_price) - avg_cost) * Decimal(sold_trade_size)


def recalculate_stop_loss(trade_info, entry_size):
    """Stop level that preserves the trade's ORIGINAL € risk on the CURRENT position.
    Original risk = |entry - initial_sl| * entry size. After a scale in/out the
    average cost and size changed, so the stop keeping that same € risk moves."""
    if not trade_info.trade_size or float(trade_info.trade_size) == 0:
        return trade_info.current_stop_loss

    risk_amount = Decimal(abs(trade_info.entry_price - trade_info.initial_stop_loss)) * Decimal(entry_size)
    risk_per_unit = risk_amount / Decimal(trade_info.trade_size)
    avg_cost = calculate_avg_cost(trade_info)

    if trade_info.position == 'Short':
        return float(avg_cost + risk_per_unit)
    return float(avg_cost - risk_per_unit)


def revert_closed_trade_cash(trade_info):
    """Undo the cash impact a closed trade had on its account (used before
    deleting a trade or replaying its steps). Marks the trade Open again."""
    if trade_info.status == 'Closed':
        net_cash_impact = Decimal(trade_info.pl) - Decimal(trade_info.commission_fee)
        trade_info.account_id.current_balance -= net_cash_impact
        trade_info.account_id.save()
        trade_info.status = 'Open'
        trade_info.save()


def replay_trade(trade_info):
    """Reset a trade to its Entry state and re-apply every remaining step in
    chronological order, refreshing each step's stored snapshots and the
    account balance. This is the single source of truth after any step is
    edited or deleted, or after the trade itself is edited."""
    revert_closed_trade_cash(trade_info)

    steps = list(TradeSteps.objects.filter(trade_id=trade_info.id).order_by('datetime'))
    entry = next((s for s in steps if s.type == 'Entry'), None)
    if entry is None:
        return

    #reset trade state from the entry step
    entry_size = entry.current_trade_size
    trade_info.trade_size = entry_size
    trade_info.total_trade_size = entry_size
    trade_info.trade_total_cost = Decimal(trade_info.entry_price) * Decimal(entry_size)
    trade_info.realized_pl = Decimal('0')
    trade_info.pl = Decimal('0')
    trade_info.status = 'Open'
    trade_info.date_closed = None
    trade_info.exit_price = None
    trade_info.trade_is_won = None
    trade_info.account_balance_post_trade = None
    trade_info.current_stop_loss = trade_info.initial_stop_loss

    #refresh entry snapshot
    entry.datetime = trade_info.date_open
    entry.current_market_price = trade_info.entry_price
    entry.current_trade_size = entry_size
    entry.current_pl = 0
    if trade_info.initial_tp:
        if trade_info.position == 'Short':
            entry.pl_if_hit = (Decimal(trade_info.entry_price) - Decimal(trade_info.initial_tp)) * Decimal(entry_size)
        else:
            entry.pl_if_hit = (Decimal(trade_info.initial_tp) - Decimal(trade_info.entry_price)) * Decimal(entry_size)
    else:
        entry.pl_if_hit = None
    entry.save()

    for s in steps:
        if s.type == 'Entry':
            continue

        if s.type == 'Trailing Stop':
            current_pl = calculate_current_pl(trade_info, trade_info.trade_size, s.current_market_price)
            s.current_trade_size = trade_info.trade_size
            s.current_pl = current_pl
            s.pl_if_hit = calculate_current_pl(trade_info, trade_info.trade_size, s.target_market_price) if s.target_market_price else None
            trade_info.pl = current_pl
            trade_info.current_stop_loss = s.target_market_price

        elif s.type == 'Scale In':
            trade_info.total_trade_size += s.trade_size_amount
            trade_info.trade_size += s.trade_size_amount
            trade_info.trade_total_cost += Decimal(s.current_market_price) * Decimal(s.trade_size_amount)
            current_pl = calculate_current_pl(trade_info, trade_info.trade_size, s.current_market_price)
            s.current_trade_size = trade_info.trade_size
            s.current_pl = current_pl
            trade_info.pl = current_pl
            trade_info.current_stop_loss = recalculate_stop_loss(trade_info, entry_size)

        elif s.type == 'Scale Out':
            trade_info.realized_pl += Decimal(calculate_realized_pl(trade_info, s.current_market_price, s.trade_size_amount))
            trade_info.trade_size -= s.trade_size_amount
            current_pl = calculate_current_pl(trade_info, trade_info.trade_size, s.current_market_price)
            s.current_trade_size = trade_info.trade_size
            s.current_pl = current_pl
            trade_info.pl = current_pl
            trade_info.current_stop_loss = recalculate_stop_loss(trade_info, entry_size)

        elif s.type == 'Stopped Out' or s.type == 'Take Profit':
            current_pl = calculate_current_pl(trade_info, trade_info.trade_size, s.current_market_price)
            net_cash_impact = Decimal(current_pl) - Decimal(trade_info.commission_fee)
            trade_info.pl = current_pl
            trade_info.date_closed = s.datetime
            trade_info.status = 'Closed'
            trade_info.exit_price = s.current_market_price
            trade_info.trade_is_won = current_pl > 0
            trade_info.account_balance_post_trade = trade_info.account_id.current_balance + net_cash_impact
            trade_info.account_id.current_balance += net_cash_impact
            trade_info.account_id.save()
            s.current_trade_size = 0
            s.current_pl = current_pl

        s.save()

    trade_info.save()



def new_trade_note(request):
    if request.method == 'POST':
        try:
            Trades.objects.filter(id=request.POST['trade_id']).update(notes=request.POST['note'])
            return redirect(f'/trade_detail?trade_id={request.POST["trade_id"]}')
        except Exception as e:
            print(request.POST, e)
            return HttpResponse(400)


def s_round(value, ndigits=2, fallback=0):
    try:
        return round(value, ndigits)
    except (TypeError, ValueError):
        return fallback