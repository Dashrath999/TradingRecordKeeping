from django.contrib import admin
from .models import Trades, TradeSteps, Accounts, LedgerNotes

# Register your models here.
admin.site.register(Trades)
admin.site.register(TradeSteps)
admin.site.register(Accounts)
admin.site.register(LedgerNotes)



