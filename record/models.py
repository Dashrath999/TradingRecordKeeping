from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator


class Accounts(models.Model):
    name = models.CharField(max_length=25, unique=True)
    initial_balance = models.DecimalField(max_digits=8, decimal_places=2)
    current_balance  = models.DecimalField(max_digits=8, decimal_places=2)
    money_secured = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)

    def __str__(self):
        return self.name
     

class Trades(models.Model):
    date_open = models.DateTimeField()
    date_closed = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=10, choices={"Open": "Open", "Closed": "Closed"}, default="Open")
    account_id = models.ForeignKey(Accounts, on_delete=models.CASCADE)
    position = models.CharField(max_length=10, choices={"Short": "Short", "Long": "Long"})
    timeframe = models.CharField(max_length=10, choices={"1w": "1w", "1d": "1d", "4h": "4h", "2h": "2h", "1h": "1h", "30m": "30m", "15m": "15m", "5m": "5m"})
    symbol = models.CharField(max_length=10)
    entry_price = models.FloatField()
    trade_size = models.FloatField()
    trade_total_cost = models.DecimalField(max_digits=8, decimal_places=2)
    total_trade_size = models.FloatField()
    exit_price = models.FloatField(blank=True, null=True)
    initial_stop_loss = models.FloatField()
    initial_tp = models.FloatField(blank=True, null=True)
    commission_fee = models.DecimalField(max_digits=8, decimal_places=2)
    pl = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True, default=0)
    realized_pl = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    risk = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(0.00), MaxValueValidator(100.00)])
    screenshot = models.ImageField(blank=True, null=True)
    account_balance_post_trade = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    trade_is_won = models.BooleanField(null=True)

class TradeSteps(models.Model):
    trade_id = models.ForeignKey(Trades, on_delete=models.CASCADE)
    datetime = models.DateTimeField()
    type = models.CharField(max_length=15, choices={"Trailing Stop": "Trailing Stop", "Entry": "Entry", "Scale In": "Scale In", "Scale Out": "Scale Out", "Stopped Out": "Stopped Out", "Take Profit": "Take Profit"})
    target_market_price = models.FloatField(null=True)
    trade_size_amount = models.FloatField(null=True)
    current_market_price = models.FloatField()
    current_trade_size = models.FloatField()
    current_pl = models.DecimalField(max_digits=8, decimal_places=2)
    pl_if_hit = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    trade_size_if_hit = models.FloatField(null=True)

class LedgerNotes(models.Model):
    notes = models.TextField()
    date_start = models.DateField()
    date_end = models.DateField()
    ledger_timeframe = models.CharField(max_length=20, choices={"All": "All", "Date Range": "Date Range", "Yearly": "Yearly", "Monthly": "Monthly", "Weekly": "Weekly", "Daily": "Daily"})
