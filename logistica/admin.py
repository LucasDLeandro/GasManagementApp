from django.contrib import admin
from .models import HistoricoStatusEntrega


@admin.register(HistoricoStatusEntrega)
class HistoricoStatusEntregaAdmin(admin.ModelAdmin):
    list_display = ('id', 'entrega', 'status_anterior', 'status_novo', 'alterado_em', 'alterado_por', 'origem')
    list_filter = ('origem', 'status_novo', 'alterado_em')
    search_fields = ('entrega__id', 'alterado_por__username')
    readonly_fields = ('entrega', 'status_anterior', 'status_novo', 'alterado_em', 'alterado_por', 'origem', 'observacoes', 'tenant')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

