from django.shortcuts import render, HttpResponse, redirect
from .forms import NewTradeForm, NewAccountForm, NewTradeStepForm
from .models import Accounts, Trades, TradeSteps
from decimal import Decimal
import yfinance as yf
import mplfinance as mpf
from pathlib import Path
from django.core.files import File
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


# BASE_DIR = Path(__file__).resolve().parent.parent

def dashboard(request):
    new_trade_form = NewTradeForm()
    new_account_form = NewAccountForm()

    accounts = []
    accounts_db = Accounts.objects.all()
    for a in accounts_db:
        accounts.append(a.name)

    #DATA REQUESTED FOR GIVEN PERIOD TODO
    #calculate total_pl
    #calculate win rate
    #calculate profit factor
    #get largest and average winning and loosing trade
    #get equity curve
    #get adequate ledger
    #get ledger note if any
    #get trades

    temp_trade = []
    temp_trades = Trades.objects.all()
    for t in temp_trades:
        temp_trade.append(t)

    return render(request, "record/dashboard.html", {'new_trade_form': new_trade_form, 'new_account_form': new_account_form, 'accounts': accounts, 'temp_trade': temp_trade})


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

                trade_info.save()

                #UPDATE ACCOUNT DATA
                trade_info.account_id.current_balance += Decimal(current_pl)
                trade_info.account_id.save()

                #CREATE NEW TRADE STEP
                TradeSteps(trade_id=trade_info, trade_size_amount=f['trade_size_amount'] ,datetime=f['datetime'], type=f['type'], current_market_price=f['current_market_price'], current_trade_size=0, current_pl=current_pl).save()

                #CREATE SCREENSHOT
                create_screenshot(trade_info)

            return redirect(f'/trade_detail?trade_id={request.POST['trade_id']}')
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
            return redirect(f'/trade_detail?trade_id={request.POST['trade_id']}')
        except Exception as e:
            print(request.POST, e)
            return HttpResponse(400)
