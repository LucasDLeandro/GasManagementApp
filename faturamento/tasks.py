import logging
import requests
from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from celery import shared_task
from core.models import Tenant
from core.tenancy import tenant_context
from faturamento.models import ConfiguracaoFiscalTenant, NotaFiscal
from faturamento.services import montar_payload_focus_nfe
from vendas.models import Venda
from clientes.models import FechamentoFaturaEstadia

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def emitir_nfe_task(self, tenant_id, entidade_id, tipo_entidade):
    """
    Task Celery assíncrona para emissão de NF-e na SEFAZ via API fiscal (Focus NFe).
    Garante execução non-blocking e retry automático em caso de timeout SEFAZ (HTTP 504).
    """
    try:
        tenant = Tenant.objects.get(id=tenant_id)
    except Tenant.DoesNotExist:
        logger.error(f"[emitir_nfe_task] Tenant {tenant_id} não encontrado.")
        return {"sucesso": False, "erro": "Tenant não encontrado"}

    with tenant_context(tenant):
        config_fiscal = ConfiguracaoFiscalTenant.objects.filter(tenant=tenant).first()

        # Localiza a entidade correspondente
        entidade = None
        if str(tipo_entidade).upper() == 'VENDA':
            entidade = Venda.objects.filter(id=entidade_id).first()
        elif str(tipo_entidade).upper() == 'ESTADIA':
            entidade = FechamentoFaturaEstadia.objects.filter(id=entidade_id).first()

        if not entidade:
            logger.error(f"[emitir_nfe_task] Entidade {tipo_entidade} #{entidade_id} não encontrada.")
            return {"sucesso": False, "erro": f"Entidade {tipo_entidade} #{entidade_id} não encontrada"}

        # Localiza ou inicializa a NotaFiscal associada
        if str(tipo_entidade).upper() == 'VENDA':
            nota_fiscal, _ = NotaFiscal.objects.get_or_create(
                tenant=tenant,
                venda=entidade,
                defaults={'valor_total': getattr(entidade, 'valor_total', Decimal('0.00'))}
            )
        else:
            nota_fiscal, _ = NotaFiscal.objects.get_or_create(
                tenant=tenant,
                fatura_estadia=entidade,
                defaults={'valor_total': getattr(entidade, 'valor_liquido_total', Decimal('0.00'))}
            )

        if not config_fiscal:
            nota_fiscal.status = 'REJEITADA'
            nota_fiscal.motivo_rejeicao = "Configuração Fiscal do Tenant não cadastrada."
            nota_fiscal.save(update_fields=['status', 'motivo_rejeicao', 'atualizado_em'])
            return {"sucesso": False, "erro": nota_fiscal.motivo_rejeicao}

        # Transição para status PROCESSANDO
        nota_fiscal.status = 'PROCESSANDO'
        nota_fiscal.save(update_fields=['status', 'atualizado_em'])

        payload = montar_payload_focus_nfe(tenant, config_fiscal, entidade, tipo_entidade)

        # Determina endpoint da Focus NFe conforme ambiente configurado
        if config_fiscal.ambiente == 'PRODUCAO':
            url_api = "https://api.focusnfe.com.br/v2/nfe"
        else:
            url_api = "https://homologacao.focusnfe.com.br/v2/nfe"

        token = config_fiscal.token_api_focus or getattr(settings, 'FOCUS_NFE_TOKEN', 'token_teste')
        auth = (token, "")

        try:
            # Envio da requisição para API externa com timeout
            response = requests.post(url_api, json=payload, auth=auth, timeout=30)
            
            # Tratamento de Timeout / Gateway Timeout (HTTP 504)
            if response.status_code == 504:
                logger.warning(f"[emitir_nfe_task] Gateway Timeout 504 retornado pela SEFAZ/Focus. Agendando retry...")
                raise self.retry(countdown=60, exc=Exception("SEFAZ Timeout (HTTP 504)"))

            if response.status_code in [200, 201, 202]:
                data = response.json()
                status_nfe = data.get('status')

                if status_nfe == 'autorizado':
                    nota_fiscal.status = 'AUTORIZADA'
                    nota_fiscal.chave_acesso = data.get('chave_nfe')
                    nota_fiscal.numero_nfe = data.get('numero')
                    nota_fiscal.xml_url = data.get('caminho_xml_nota_fiscal')
                    nota_fiscal.danfe_url = data.get('caminho_danfe')
                    nota_fiscal.data_emissao = timezone.now()
                    nota_fiscal.motivo_rejeicao = None
                elif status_nfe == 'processando_autorizacao':
                    nota_fiscal.status = 'PROCESSANDO'
                    nota_fiscal.chave_acesso = data.get('chave_nfe')
                else:
                    nota_fiscal.status = 'REJEITADA'
                    nota_fiscal.motivo_rejeicao = str(data.get('mensagem_sefaz') or data.get('erros') or status_nfe)

                nota_fiscal.save()
                return {"sucesso": True, "status": nota_fiscal.status, "chave": nota_fiscal.chave_acesso}

            else:
                nota_fiscal.status = 'REJEITADA'
                nota_fiscal.motivo_rejeicao = f"Erro HTTP {response.status_code}: {response.text}"
                nota_fiscal.save()
                return {"sucesso": False, "status": nota_fiscal.status, "motivo": nota_fiscal.motivo_rejeicao}

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            logger.warning(f"[emitir_nfe_task] Exceção de rede ({exc}). Agendando retry...")
            raise self.retry(countdown=60, exc=exc)
        except Exception as exc:
            if hasattr(self, 'request') and self.request.retries >= self.max_retries:
                nota_fiscal.status = 'REJEITADA'
                nota_fiscal.motivo_rejeicao = f"Tentativas esgotadas: {exc}"
                nota_fiscal.save()
            raise exc
