from django.contrib import admin
from .models import HistoricoStatusVenda


@admin.register(HistoricoStatusVenda)
class HistoricoStatusVendaAdmin(admin.ModelAdmin):
    list_display = ('id', 'venda', 'status_anterior', 'status_novo', 'alterado_em', 'alterado_por', 'origem')
    list_filter = ('origem', 'status_novo', 'alterado_em')
    search_fields = ('venda__id', 'venda__cliente__nome', 'alterado_por__username')
    readonly_fields = ('venda', 'status_anterior', 'status_novo', 'alterado_em', 'alterado_por', 'origem', 'observacoes', 'tenant')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

