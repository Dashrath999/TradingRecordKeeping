from django.contrib import admin
from django.urls import path, include
from . import views
from django.conf.urls.static import static
from django.conf import settings

urlpatterns = [
    path('', views.dashboard, name='record-dashboard'),
    path('loaddata', views.loaddata, name='record-loaddata'),

    path('new_trade', views.new_trade, name='record-new-trade'),
    path('edit_trade', views.edit_trade, name='record-edit-trade'),
    path('delete_trade', views.delete_trade, name='record-delete-trade'),
    path('new_account', views.new_account, name='record-new-account'),
    path('new_ledger_note', views.new_ledger_note, name='record-new-ledger-note'),


    path('trade_detail', views.trade_detail, name='record-trade-detail'),
    path('new_trade_step', views.new_trade_step, name='record-new-trade-step'),
    path('edit_trade_step', views.edit_trade_step, name='record-edit-trade-step'),
    path('delete_trade_step', views.delete_trade_step, name='record-delete-trade-step'),
    path('new_trade_note', views.new_trade_note, name='record-new-trade-note'),
]

urlpatterns += static(settings.MEDIA_URL, document_root = settings.MEDIA_ROOT)