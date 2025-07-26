from django.shortcuts import render, HttpResponse, redirect
from .forms import NewTradeForm, NewAccountForm
from .models import Accounts, Trades, TradeSteps
from decimal import Decimal

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
            
            #TODO CREATE INITIAL SCREENSHOT WITH ENTRY, SL AND TP? MARKERS

            trade_size, trade_total_cost = calculate_trade_size_and_cost(f['account_id'].current_balance, f['risk'], f['entry_price'], f['initial_stop_loss'], f['commission_fee'])
            Trades(date_open=f['date_open'], account_id=f['account_id'], position=f['position'], timeframe=f['timeframe'], symbol=f['symbol'], entry_price=f['entry_price'], trade_size=trade_size, trade_total_cost=trade_total_cost, initial_stop_loss=f['initial_stop_loss'], initial_tp=f['initial_tp'], commission_fee=f['commission_fee'], risk=f['risk']).save()

            return redirect('record-dashboard')
        else:
            return HttpResponse(400)


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
    
    trade_info = Trades.objects.filter(id=trade_id).all()
    trade_steps = TradeSteps.objects.filter(id=trade_id).order_by('datetime').all()

    return render(request, "record/trade_detail.html", {'trade_info': trade_info, 'trade_steps': trade_steps})