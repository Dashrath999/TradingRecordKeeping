from django.contrib import admin
from django.urls import path, include
from . import views
from django.conf.urls.static import static
from django.conf import settings

urlpatterns = [
    path('', views.dashboard, name='record-dashboard'),
    path('new_trade', views.new_trade, name='record-new-trade'),
    path('new_account', views.new_account, name='record-new-account'),

    path('trade_detail', views.trade_detail, name='record-trade-detail'),
    path('new_trade_step', views.new_trade_step, name='record-new-trade-step'),
]

urlpatterns += static(settings.MEDIA_URL, document_root = settings.MEDIA_ROOT)