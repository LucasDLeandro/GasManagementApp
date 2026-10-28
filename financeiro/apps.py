from django.apps import AppConfig


class FinanceiroConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'financeiro'
    verbose_name = 'Financeiro e Contabilidade'

    def ready(self):
        try:
            from core.eventos import assinar
            from financeiro.contabilizacao import processar_evento_financeiro, HANDLERS_CONTABILIZACAO

            for nome_evento in HANDLERS_CONTABILIZACAO.keys():
                def make_handler(evt):
                    def _h(payload):
                        return processar_evento_financeiro(evt, payload)
                    _h.__name__ = f"handler_financeiro_{evt}"
                    return _h

                assinar(nome_evento, make_handler(nome_evento))
        except Exception:
            pass
