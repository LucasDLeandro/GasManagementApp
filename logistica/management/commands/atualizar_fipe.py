import datetime
from django.db import models
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.cache import cache
from logistica.models import Veiculo, VeiculoValorFipe
from logistica.services.fipe import (
    obter_valor_fipe,
    obter_valor_por_codigo_fipe
)

class Command(BaseCommand):
    help = "Atualiza o valor de mercado FIPE dos veículos cadastrados com código FIPE respeitando limites de requisições."

    def add_arguments(self, parser):
        parser.add_argument(
            '--limite-reqs',
            type=int,
            default=450,
            help="Limite máximo de requisições à API FIPE nesta execução (padrão 450 para respeitar teto de 500/dia)."
        )
        parser.add_argument(
            '--tenant',
            type=str,
            default=None,
            help="Filtrar por ID de um Tenant específico."
        )

    def handle(self, *args, **options):
        limite_reqs = options['limite_reqs']
        tenant_id = options.get('tenant')

        hoje_str = timezone.localdate().isoformat()
        cache_key_dia = f"fipe_reqs_consumidas_{hoje_str}"
        reqs_consumidas_hoje = cache.get(cache_key_dia, 0)

        vagas_restantes = max(0, limite_reqs - reqs_consumidas_hoje)
        if vagas_restantes <= 0:
            self.stdout.write(self.style.WARNING(
                f"Limite diário de requisições FIPE já atingido para hoje ({reqs_consumidas_hoje} requisições). "
                f"A execução será retomada amanhã."
            ))
            return

        veiculos_qs = Veiculo.unscoped.filter(fipe_codigo__isnull=False).exclude(fipe_codigo='')
        if tenant_id:
            veiculos_qs = veiculos_qs.filter(tenant_id=tenant_id)

        # Prioriza veículos nunca atualizados ou com atualização mais antiga
        veiculos = list(veiculos_qs.order_by(
            models.F('fipe_atualizado_em').asc(nulls_first=True)
        )[:vagas_restantes])

        if not veiculos:
            self.stdout.write(self.style.SUCCESS("Nenhum veículo pendente de atualização FIPE encontrado."))
            return

        self.stdout.write(f"Iniciando atualização FIPE para {len(veiculos)} veículo(s)...")

        sucessos = 0
        falhas = 0
        limite_atingido = False

        for veiculo in veiculos:
            tipo = veiculo.fipe_tipo or 'caminhoes'
            
            sucesso = False
            dados = None
            erro = ""

            if veiculo.fipe_marca_codigo and veiculo.fipe_modelo_codigo and veiculo.fipe_ano_codigo:
                sucesso, dados, erro = obter_valor_fipe(
                    tipo=tipo,
                    marca_codigo=veiculo.fipe_marca_codigo,
                    modelo_codigo=veiculo.fipe_modelo_codigo,
                    ano_codigo=veiculo.fipe_ano_codigo
                )
            else:
                sucesso, dados, erro = obter_valor_por_codigo_fipe(
                    tipo=tipo,
                    fipe_codigo=veiculo.fipe_codigo,
                    ano_codigo=veiculo.fipe_ano_codigo
                )

            reqs_consumidas_hoje += 1
            cache.set(cache_key_dia, reqs_consumidas_hoje, 60 * 60 * 24)

            if sucesso and dados and dados.get('valor_decimal'):
                novo_valor = dados['valor_decimal']
                mes_ref = dados.get('referenceMonth') or f"{timezone.localdate().strftime('%B/%Y')}"
                
                veiculo.fipe_valor = novo_valor
                veiculo.fipe_mes_referencia = mes_ref
                veiculo.fipe_atualizado_em = timezone.now()
                if not veiculo.fipe_marca_nome and dados.get('brand'):
                    veiculo.fipe_marca_nome = dados['brand']
                if not veiculo.fipe_modelo_nome and dados.get('model'):
                    veiculo.fipe_modelo_nome = dados['model']
                veiculo.save()

                # Snapshot no histórico de depreciação mensal
                VeiculoValorFipe.unscoped.update_or_create(
                    tenant=veiculo.tenant,
                    veiculo=veiculo,
                    mes_referencia=mes_ref,
                    defaults={'valor': novo_valor}
                )

                sucessos += 1
                self.stdout.write(self.style.SUCCESS(
                    f"[OK] Veiculo {veiculo.placa}: R$ {novo_valor} ({mes_ref})"
                ))
            else:
                falhas += 1
                self.stdout.write(self.style.ERROR(
                    f"[ERRO] Veiculo {veiculo.placa} (FIPE {veiculo.fipe_codigo}): {erro}"
                ))
                if "429" in str(erro) or "Limite diário" in str(erro):
                    limite_atingido = True
                    break

        self.stdout.write(self.style.SUCCESS(
            f"Processamento concluído. Sucessos: {sucessos}, Falhas: {falhas}. "
            f"Total de requisições FIPE consumidas hoje: {reqs_consumidas_hoje}."
        ))
        if limite_atingido:
            self.stdout.write(self.style.WARNING("Cota da API atingida; retomada automática agendada para amanhã."))
