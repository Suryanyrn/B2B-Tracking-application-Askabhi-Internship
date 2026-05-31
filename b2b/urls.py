from django.contrib import admin
from django.urls import path, include
from b2bapp.admin import admin_site

urlpatterns = [
    path('admin/', admin_site.urls),
    path('', include('b2bapp.urls'))
]
