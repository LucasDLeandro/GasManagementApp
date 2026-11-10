from django.contrib import admin
from .models import HistoricoQualidadeLote


@admin.register(HistoricoQualidadeLote)
class HistoricoQualidadeLoteAdmin(admin.ModelAdmin):
    list_display = ['lote', 'status_anterior', 'status_novo', 'rt_nome_snapshot', 'criado_em']
    readonly_fields = [
        'tenant', 'lote', 'status_anterior', 'status_novo', 'justificativa',
        'usuario', 'responsavel_tecnico', 'rt_nome_snapshot', 'rt_registro_snapshot', 'criado_em'
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

