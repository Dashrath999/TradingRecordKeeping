from django.shortcuts import render, HttpResponse, redirect
from .forms import NewTradeForm, NewAccountForm, NewTradeStepForm
from .models import Accounts, Trades, TradeSteps, LedgerNotes
from decimal import Decimal
import yfinance as yf
import mplfinance as mpf
from pathlib import Path
from django.core.files import File
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from django.db.models import Sum, Avg
from django.http import JsonResponse
from calendar import monthrange


#STILL LEFT TODO
# DEPLOY (+ LOGIN IF NEEDED)
# MAKE RESPONSIVE
# EDIT REMOVE TRADE AND TRADE STEPS
# RECALCULATE STOP LOSS AFTER SCALE IN OR SCALE OUT
# DON'T REDIRECT WHEN LEDGER NOTE IS ADDEDFOR BETTER UX
# IN GET EQUITY CURVE, GET THE ACCOUNT BALANCE BEFORE THE FIRST POINT, NOT 0 LIKE NOW
# KEEP ALL THE GENERATED PLOT AND BUTTON TO SEE THEM ALL

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

    json_resp['won_trade_percent'] = s_round((total_nb_trades_win / total_nb_trades_closed) * 100, 2) if total_nb_trades_closed > 0 else 100

    #calculate profit factor
    gross_profit = time_frame_closed_trades.filter(trade_is_won=True).aggregate(total=Sum('pl'))['total']
    gross_loss = time_frame_closed_trades.filter(trade_is_won=False).aggregate(total=Sum('pl'))['total']

    if gross_loss == None or gross_profit == None:
        json_resp['profit_factor'] = '∞'
    else:
        json_resp['profit_factor'] = s_round(gross_profit / gross_loss, 2) if gross_loss != 0 else '∞'


    #get largest and average winning and loosing trade
    max_trade = time_frame_closed_trades.order_by('-pl').first()
    json_resp['max_trade'] = (s_round(max_trade.pl, 2), s_round(max_trade.id, 2)) if max_trade != None and max_trade.pl > 0 else 'N/A'

    min_trade = time_frame_closed_trades.order_by('pl').first()
    json_resp['min_trade'] = (s_round(min_trade.pl, 2), s_round(min_trade.id, 2)) if min_trade != None and min_trade.pl < 0 else 'N/A'

    json_resp['avg_win'] = s_round(time_frame_closed_trades.filter(trade_is_won=True).aggregate(avg=Avg('pl'))['avg'], 2) if time_frame_closed_trades.filter(trade_is_won=True).aggregate(avg=Avg('pl'))['avg'] != None else 'N/A'
    json_resp['avg_lost'] = s_round(time_frame_closed_trades.filter(trade_is_won=False).aggregate(avg=Avg('pl'))['avg'], 2) if time_frame_closed_trades.filter(trade_is_won=False).aggregate(avg=Avg('pl'))['avg'] != None else 'N/A'

    #get equity curve
    json_resp['equity_curve_labels'], json_resp['equity_curve_data'] = get_equity_curve_labels_and_data(time_frame, time_frame_closed_trades, date)

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

            # return HttpResponse(200) TODO DON'T REDIRECT FOR BETTER UX
            return redirect('record-dashboard')
        
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


    elif 'Daily':
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


def get_equity_curve_labels_and_data(time_frame, time_frame_closed_trades, date): #TODO GET ACCOUNT BALANCE PRE TIMEFRAME (NOT = 0 LIKE NOW)

    if time_frame == 'All' or time_frame == 'Date Range':
        labels = []
        data = []
        for t in time_frame_closed_trades:
            labels.append(t.date_closed)
            data.append(t.account_balance_post_trade)

    elif time_frame == 'Yearly':
        day, month, year = date.split('.')
        labels = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
        data = []
        latest_trade_of_month_account_balance = 0
        for i in range(1,13):
            if len(time_frame_closed_trades.filter(date_closed__year=year, date_closed__month=i)) > 0:
                latest_trade_of_month_account_balance = time_frame_closed_trades.filter(date_closed__year=year, date_closed__month=i).latest('date_closed').account_balance_post_trade
            
            data.append(latest_trade_of_month_account_balance)

    elif time_frame == 'Monthly':
        day, month, year = date.split('.')
        month_range = monthrange(int(year), int(month))[1]
        labels = list(range(1, month_range + 1))

        data = []
        latest_trade_of_day_account_balance = 0
        for i in range(1, month_range + 1):
            if len(time_frame_closed_trades.filter(date_closed__year=year, date_closed__month=month, date_closed__day=i)) > 0:
                latest_trade_of_day_account_balance = time_frame_closed_trades.filter(date_closed__year=year, date_closed__month=month, date_closed__day=i).latest('date_closed').account_balance_post_trade

            data.append(latest_trade_of_day_account_balance)

    elif time_frame == 'Daily':
        day, month, year = date.split('.')
        
        labels = []
        data = []
        latest_trade_of_hour_account_balance = 0
        for i in range(24):
            labels.append(i)
            if len(time_frame_closed_trades.filter(date_closed__year=year, date_closed__month=month, date_closed__day=day, date_closed__hour=i)) > 0:
                latest_trade_of_hour_account_balance = time_frame_closed_trades.filter(date_closed__year=year, date_closed__month=month, date_closed__day=day, date_closed__hour=i).latest('date_closed').account_balance_post_trade

            data.append(latest_trade_of_hour_account_balance)

    return labels, data


def new_trade(request):
    if request.method == 'POST':
        f = NewTradeForm(request.POST)
        if f.is_valid():
            f = f.cleaned_data

            #GET TRADE_SIZE AND TRADE_TOTAL_COST
            trade_size, trade_total_cost = calculate_trade_size_and_cost(f['account_id'].current_balance, f['risk'], f['entry_price'], f['initial_stop_loss'], f['commission_fee'])

            #CREATE NEW_TRADE
            new_trade = Trades(date_open=f['date_open'], account_id=f['account_id'], position=f['position'], timeframe=f['timeframe'], symbol=f['symbol'], entry_price=f['entry_price'], trade_size=trade_size, total_trade_size=trade_size, trade_total_cost=trade_total_cost, initial_stop_loss=f['initial_stop_loss'], initial_tp=f['initial_tp'], commission_fee=f['commission_fee'], risk=f['risk'], notes='')
            new_trade.save()

            #CREATE ENTRY TRADE STEP
            pl_if_hit = (Decimal(new_trade.initial_tp) * Decimal(new_trade.trade_size)) - (Decimal(new_trade.entry_price) * Decimal(new_trade.trade_size)) if new_trade.initial_tp else None
            TradeSteps(trade_id=new_trade, datetime=f['date_open'], type="Entry", current_market_price=f['entry_price'], current_trade_size=trade_size, current_pl=0, pl_if_hit=pl_if_hit).save()

            #CREATE INITIAL SCREENSHOT WITH ENTRY, SL AND TP? MARKERS
            create_screenshot(new_trade)

            return redirect('record-dashboard')
        else:
            return HttpResponse(400)


def create_screenshot(trade_info):
    ticker = yf.Ticker(trade_info.symbol)
    ap = []

    #get time period to look at
    time_delta_days ={"1w": 21, "1d": 5, "4h": 3, "2h": 2, "1h": 2, "30m": 1, "15m": 1, "5m": 1}
    start_date = trade_info.date_open - timedelta(days=time_delta_days[trade_info.timeframe])
    end_date = datetime.now() if trade_info.date_closed == None else trade_info.date_closed + timedelta(days=time_delta_days[trade_info.timeframe])
    data = ticker.history(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"), interval=trade_info.timeframe)

    #make entry signal addplot
    entry_signal = [trade_info.date_open.strftime("%Y-%m-%d")]
    entry_series = pd.Series(index=data.index, data=np.nan)
    if entry_signal[0] in data.index:
        entry_series[entry_signal[0]] = data.loc[entry_signal[0], "Close"]
    ap.append(mpf.make_addplot(entry_series, type='scatter', markersize=100, marker='o', color='g'))

    #create sl and tp horizontal line
    hlines = {}
    hlines['hlines'] = [trade_info.initial_stop_loss, trade_info.initial_tp] if trade_info.initial_tp else [trade_info.initial_stop_loss]
    hlines['colors'] = ['r', 'g'] if trade_info.initial_tp else ['r']
    hlines['linestyle'] = '-.'

    #ITERATE THROUGH RELEVANT TRADE_STEPS TO MARK THEM ON THE PLOT
    trade_steps = TradeSteps.objects.filter(trade_id=trade_info.id).order_by('datetime').all()

    trailling_stop_points = []
    for t in trade_steps:
        if t.type == 'Trailing Stop':
            trailing_stop_price = t.target_market_price
            trailing_stop_start_date = t.datetime.strftime("%Y-%m-%d")
            traling_stop_end_date = data.index[-1]
            trailling_stop_points.append([(trailing_stop_start_date, trailing_stop_price), (traling_stop_end_date, trailing_stop_price)])

        elif t.type == 'Scale In':
            scale_in_signal = [t.datetime.strftime("%Y-%m-%d")]
            scale_in_series = pd.Series(index=data.index, data=np.nan)
            if scale_in_signal[0] in data.index:
                scale_in_series[scale_in_signal[0]] = data.loc[scale_in_signal[0], "Close"]
            ap.append(mpf.make_addplot(scale_in_series, type='scatter', markersize=100, marker='^', color='c'))

        elif t.type == 'Scale Out':
            scale_out_signal = [t.datetime.strftime("%Y-%m-%d")]
            scale_out_series = pd.Series(index=data.index, data=np.nan)
            if scale_out_signal[0] in data.index:
                scale_out_series[scale_out_signal[0]] = data.loc[scale_out_signal[0], "Close"]
            ap.append(mpf.make_addplot(scale_out_series, type='scatter', markersize=100, marker='v', color='c'))

        elif t.type == 'Stopped Out':
            stopped_out_signal = [t.datetime.strftime("%Y-%m-%d")]
            stopped_out_series = pd.Series(index=data.index, data=np.nan)
            if stopped_out_signal[0] in data.index:
                stopped_out_series[stopped_out_signal[0]] = data.loc[stopped_out_signal[0], "Close"]
            ap.append(mpf.make_addplot(stopped_out_series, type='scatter', markersize=100, marker='x', color='r'))

        elif t.type == 'Take Profit':
            take_profit_signal = [t.datetime.strftime("%Y-%m-%d")]
            take_profit_series = pd.Series(index=data.index, data=np.nan)
            if take_profit_signal[0] in data.index:
                take_profit_series[take_profit_signal[0]] = data.loc[take_profit_signal[0], "Close"]
            ap.append(mpf.make_addplot(take_profit_series, type='scatter', markersize=100, marker='x', color='g'))

    #save plot to filesystem #TODO KEEP ALL THE GENERATED PLOTS AND GIVE OPTION TO USER TO SEE THEM
    mpf.plot(data, type='candle', style='yahoo', volume=True, savefig=f'trade_screenshots/trade_{trade_info.id}', addplot=ap, hlines=hlines, alines=dict(alines=trailling_stop_points, colors=['c']))
    path = Path(f'trade_screenshots/trade_{trade_info.id}.png')
    with path.open(mode="rb") as file:
        Trades.objects.filter(id=trade_info.id).update(screenshot=File(file, name=path.name)) 



def calculate_trade_size_and_cost(account_balance, risk, entry_price, stop_loss, commision):
    risk_amount = Decimal(account_balance * (risk / 100))

    stop_loss_per_unit = Decimal(abs(entry_price - stop_loss))

    trade_size = Decimal(risk_amount / stop_loss_per_unit)
    trade_total_cost = (trade_size * Decimal(entry_price)) + commision

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
    trade_note = trade_info[0].notes
    trade_steps = TradeSteps.objects.filter(trade_id=trade_id).order_by('datetime').all()

    return render(request, "record/trade_detail.html", {'trade_info': trade_info, 'trade_steps': trade_steps, 'new_trade_step_form': new_trade_step_form, 'trade_id': trade_id, 'trade_note': trade_note})


def new_trade_step(request): #TODO RECALCULATE STOP_LOSS AFTER SCALE IN OR SCALE OUT
    if request.method == 'POST':
        f = NewTradeStepForm(request.POST)
        if f.is_valid() and request.POST['trade_id']:
            f = f.cleaned_data
            last_trade_step_data = TradeSteps.objects.filter(trade_id=request.POST['trade_id']).latest('datetime')
            trade_info = Trades.objects.filter(id=request.POST['trade_id']).first()

            if f['type'] == 'Trailing Stop':
                #CREATE NEW TRADE STEP
                current_pl = calculate_current_pl(trade_info, last_trade_step_data.current_trade_size, f['current_market_price'])
                pl_if_hit = calculate_current_pl(trade_info, last_trade_step_data.current_trade_size, f['target_market_price'])
                TradeSteps(trade_id=trade_info, target_market_price=f['target_market_price'], trade_size_amount=f['trade_size_amount'] ,datetime=f['datetime'], type=f['type'], current_market_price=f['current_market_price'], current_trade_size=last_trade_step_data.current_trade_size, current_pl=current_pl, trade_size_if_hit=0, pl_if_hit=pl_if_hit).save()

                #CREATE SCREENSHOT
                create_screenshot(trade_info)

                #UPDATE TRADE_INFO
                trade_info.pl = current_pl
                trade_info.save()

            elif f['type'] == 'Scale In':
                #UPDATE TRADE_INFO
                trade_info.total_trade_size += f['trade_size_amount']
                trade_info.trade_size += f['trade_size_amount']
                trade_info.trade_total_cost += Decimal(f['current_market_price']) * Decimal(f['trade_size_amount'])
                current_pl = calculate_current_pl(trade_info, last_trade_step_data.current_trade_size, f['current_market_price'])
                trade_info.pl = current_pl

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

                trade_info.save()
                
                #CREATE NEW TRADE STEP
                TradeSteps(trade_id=trade_info, trade_size_amount=f['trade_size_amount'] ,datetime=f['datetime'], type=f['type'], current_market_price=f['current_market_price'], current_trade_size=trade_info.trade_size, current_pl=current_pl).save()

                #CREATE SCREENSHOT
                create_screenshot(trade_info)

            elif f['type'] == 'Stopped Out' or f['type'] == 'Take Profit':
                #UPDATE TRADE_INFO
                current_pl = calculate_current_pl(trade_info, last_trade_step_data.current_trade_size, f['current_market_price'])
                trade_info.pl = current_pl
                trade_info.date_closed = f['datetime']
                trade_info.status = 'Closed'
                trade_info.exit_price = f['current_market_price']
                trade_info.trade_is_won = True if current_pl > 0 else False
                trade_info.account_balance_post_trade = trade_info.account_id.current_balance + Decimal(current_pl)

                trade_info.save()

                #UPDATE ACCOUNT DATA
                trade_info.account_id.current_balance += Decimal(current_pl)
                trade_info.account_id.save()

                #CREATE NEW TRADE STEP
                TradeSteps(trade_id=trade_info, trade_size_amount=f['trade_size_amount'] ,datetime=f['datetime'], type=f['type'], current_market_price=f['current_market_price'], current_trade_size=0, current_pl=current_pl).save()

                #CREATE SCREENSHOT
                create_screenshot(trade_info)

            return redirect(f'/trade_detail?trade_id={request.POST["trade_id"]}')
        else:
            return HttpResponse(400)

def calculate_current_pl(trade_info, current_trade_size, current_market_price):
    #CALCULATE AVERAGE COST
    avg_cost = Decimal(trade_info.trade_total_cost) / Decimal(trade_info.total_trade_size)

    #CALCULATE UNREALIZED PL
    unrealized_pl = (Decimal(current_market_price) - avg_cost) * Decimal(current_trade_size)

    return unrealized_pl + trade_info.realized_pl


def calculate_realized_pl(trade_info, current_market_price, sold_trade_size):
    #CALCULATE AVERAGE COST
    avg_cost = Decimal(trade_info.trade_total_cost) / Decimal(trade_info.trade_size)

    return (Decimal(current_market_price) - Decimal(avg_cost)) * Decimal(sold_trade_size)



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