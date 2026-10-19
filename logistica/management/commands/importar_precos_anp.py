import os
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Tenant
from logistica.services.anp import (
    baixar_csv_anp,
    importar_precos_anp_de_conteudo,
    DEFAULT_ANP_URLS
)


class Command(BaseCommand):
    help = "Importa preços médios de referência de combustíveis a partir dos Dados Abertos da ANP (LPC - CSV)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--uf',
            type=str,
            default=None,
            help="Filtrar por Unidade da Federação (ex: GO, SP, RJ, DF)."
        )
        parser.add_argument(
            '--municipio',
            type=str,
            default=None,
            help="Filtrar por nome de Município específico."
        )
        parser.add_argument(
            '--arquivo',
            type=str,
            default=None,
            help="Caminho para arquivo CSV local da ANP (útil para operação offline/rede restrita)."
        )
        parser.add_argument(
            '--url',
            type=str,
            default=None,
            help="URL customizada para download do arquivo CSV da ANP."
        )
        parser.add_argument(
            '--grupo',
            type=str,
            choices=['DIESEL_GNV', 'GASOLINA_ETANOL', 'GLP', 'TODOS'],
            default='TODOS',
            help="Grupo de combustíveis para download automático quando --arquivo não for fornecido."
        )
        parser.add_argument(
            '--tenant',
            type=str,
            default=None,
            help="ID do Tenant específico para vincular os preços importados."
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Simula a leitura e validação do CSV sem gravar alterações no banco de dados."
        )

    def handle(self, *args, **options):
        uf_filtro = options.get('uf')
        municipio_filtro = options.get('municipio')
        caminho_arquivo = options.get('arquivo')
        url_custom = options.get('url')
        grupo = options.get('grupo')
        tenant_id = options.get('tenant')
        dry_run = options.get('dry_run', False)

        # Seleciona o tenant alvo
        if tenant_id:
            tenants = list(Tenant.objects.filter(id=tenant_id))
        else:
            tenants = list(Tenant.objects.all()[:1])
            if not tenants:
                self.stdout.write(self.style.ERROR("[ERRO] Nenhum Tenant encontrado na base."))
                return

        alvo_tenant = tenants[0]
        self.stdout.write(f"Iniciando importacao ANP para o Tenant: {alvo_tenant.nome_fantasia or alvo_tenant.razao_social}...")
        if dry_run:
            self.stdout.write(self.style.WARNING("MODO DRY-RUN ATIVADO: Nenhuma alteracao sera gravada."))

        arquivos_para_processar = []

        if caminho_arquivo:
            if not os.path.exists(caminho_arquivo):
                self.stdout.write(self.style.ERROR(f"[ERRO] Arquivo local nao encontrado: {caminho_arquivo}"))
                return
            with open(caminho_arquivo, 'rb') as f:
                arquivos_para_processar.append(('Arquivo Local', f.read()))
        else:
            # Baixa da internet
            urls_alvo = []
            if url_custom:
                urls_alvo.append(('URL Customizada', url_custom))
            elif grupo == 'TODOS':
                urls_alvo = list(DEFAULT_ANP_URLS.items())
            else:
                urls_alvo = [(grupo, DEFAULT_ANP_URLS[grupo])]

            for nome_grupo, u in urls_alvo:
                self.stdout.write(f"Baixando base ANP ({nome_grupo})...")
                try:
                    conteudo = baixar_csv_anp(u)
                    arquivos_para_processar.append((nome_grupo, conteudo))
                    self.stdout.write(self.style.SUCCESS(f"[OK] Download concluido: {nome_grupo} ({len(conteudo) // 1024} KB)"))
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"[AVISO] Falha ao baixar {nome_grupo}: {str(e)}"))

        if not arquivos_para_processar:
            self.stdout.write(self.style.ERROR("[ERRO] Nenhum dado disponivel para processar."))
            return

        total_criados = 0
        total_atualizados = 0
        total_ignorados = 0

        for nome, raw_bytes in arquivos_para_processar:
            self.stdout.write(f"Processando registros de {nome}...")
            try:
                res = importar_precos_anp_de_conteudo(
                    raw_bytes,
                    uf_filtro=uf_filtro,
                    municipio_filtro=municipio_filtro,
                    tenant=alvo_tenant,
                    dry_run=dry_run
                )
                total_criados += res['criados']
                total_atualizados += res['atualizados']
                total_ignorados += res['ignorados']

                self.stdout.write(self.style.SUCCESS(
                    f"Concluido {nome}: {res['criados']} criados, {res['atualizados']} atualizados, {res['ignorados']} ignorados."
                ))
                if res['erros']:
                    for err in res['erros'][:5]:
                        self.stdout.write(self.style.WARNING(f"  - {err}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"[ERRO] Falha ao processar {nome}: {str(e)}"))

        self.stdout.write(self.style.SUCCESS(
            f"\nResumo da Importacao ANP: "
            f"Criados: {total_criados} | Atualizados: {total_atualizados} | Ignorados: {total_ignorados} "
            f"({'SIMULACAO - DRY RUN' if dry_run else 'GRAVADO COM SUCESSO'})."
        ))
