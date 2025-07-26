from django.contrib import admin
from django.urls import path, include
from . import views

urlpatterns = [
    path('', views.dashboard, name='record-dashboard'),
    path('new_trade', views.new_trade, name='record-new-trade'),
    path('new_account', views.new_account, name='record-new-account'),

    path('trade_detail', views.trade_detail, name='record-trade-detail')
]