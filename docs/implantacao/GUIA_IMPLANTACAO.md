# Guia Oficial de Implantação, Carga de Dados e Rollout Controlado

**Projeto:** Baros - Sistema de Gestão para Distribuidores de Gases do Ar e GLP  
**Versão:** 1.0.0 (Sprint 13 - Homologação Go-Live)  
**Data:** 2026-10-27  
**Classificação:** Operações, Engenharia & Implantação  

---

## 1. Visão Geral da Estratégia de Rollout

A implantação do Baros em novas distribuidoras adota uma estratégia estritamente controlada e progressiva baseada em **Tenant Piloto** e **Feature Flags Granulares** (`core.services.rollout_service`):

1. **Ativação por Módulo:**
   - Módulo `base`: Cadastros gerais, usuários, filiais e produtos (sempre ativo).
   - Módulo `financeiro`: Títulos, parcelas, bancos, conciliação e DRE.
   - Módulo `logistica`: Roteirização, frotas, motoristas e entregas.
   - Módulo `fiscal`: Emissão de NF-e, MDF-e, CT-e e contingência SEFAZ.
   - Módulo `portal_b2b`: Autoatendimento para clientes finais.
   - Módulo `analytics`: Previsão estatística de demanda e churn.
2. **Ambiente de Homologação (Staging):**
   - Carga prévia de base anonimizada com histórico operacional dos últimos 3 meses.
   - Validação de regras e conciliações antes da virada definitiva.

---

## 2. Scripts Versionados de Carga de Dados Legados

Todas as cargas de dados legados são executadas através do serviço unificado `core.services.carga_legado_service`, com suporte a modo simulação (`dry_run=True`), transações atômicas e chave de idempotência:

### 2.1. Carga de Clientes e Fornecedores
```bash
python manage.py shell -c "
from core.models import Tenant
from core.services.carga_legado_service import carregar_clientes_legado, carregar_fornecedores_legado
import json

tenant = Tenant.objects.get(cnpj='12.345.678/0001-90')

with open('dados_migracao/clientes.json', 'r', encoding='utf-8') as f:
    dados_clientes = json.load(f)

# 1. Executar primeiro em Dry-Run para validar consistência
res_sim = carregar_clientes_legado(tenant, dados_clientes, dry_run=True)
print('Validação de Clientes:', res_sim)

# 2. Executar carga definitiva
res_def = carregar_clientes_legado(tenant, dados_clientes, dry_run=False)
print('Carga Definitiva de Clientes:', res_def)
"
```

### 2.2. Carga do Parque de Cilindros e Ativos Imobilizados
```bash
python manage.py shell -c "
from core.models import Tenant
from core.services.carga_legado_service import carregar_cilindros_legado
import json

tenant = Tenant.objects.get(cnpj='12.345.678/0001-90')

with open('dados_migracao/cilindros.json', 'r', encoding='utf-8') as f:
    dados_cilindros = json.load(f)

res = carregar_cilindros_legado(tenant, dados_cilindros, dry_run=False)
print('Carga de Cilindros:', res)
"
```

### 2.3. Carga do Saldo de Abertura Contábil (Balanço de Abertura)
```bash
python manage.py shell -c "
from core.models import Tenant
from core.services.carga_legado_service import carregar_saldo_abertura_contabil
import json

tenant = Tenant.objects.get(cnpj='12.345.678/0001-90')

with open('dados_migracao/saldo_abertura.json', 'r', encoding='utf-8') as f:
    dados_abertura = json.load(f)

# Valida automaticamente o invariante Débito = Crédito antes de gravar no Razão
res_contabil = carregar_saldo_abertura_contabil(tenant, dados_abertura, dry_run=False)
print('Saldo de Abertura Contábil:', res_contabil)
"
```

---

## 3. Plano de Rollback por Módulo (Plano de Contingência)

Caso um módulo em rollout piloto apresente comportamento anômalo ou gere impedimento operacional, a equipe pode acionar o rollback atômico sem afetar os dados dos demais módulos:

### 3.1. Procedimento de Rollback no Staging / Produção
1. **Desativação Imediata da Feature Flag:**
   ```bash
   python manage.py shell -c "
   from core.models import Tenant
   from core.services.rollout_service import desativar_feature_piloto
   tenant = Tenant.objects.get(cnpj='12.345.678/0001-90')
   desativar_feature_piloto(tenant, 'portal_b2b', usuario_responsavel=user)
   print('Módulo portal_b2b desativado com sucesso.')
   "
   ```
2. **Reversão Atômica de Dados Operacionais:**
   - O serviço `executar_rollback_modulo(tenant, modulo, ponto_restauracao)` isola transações geradas pelo módulo, move registros pendentes para quarentena e estorna contabilizações correspondentes através de contrapartidas contábeis auditadas.
3. **Manutenção do Isolamento:**
   - O rollback de um módulo (ex: `logistica`) jamais exclui cadastros base de clientes ou títulos financeiros já liquidados.

---

## 4. Checklist Formal de Go-Live (Critérios de Aceite Assinados)

O go-live é formalmente liberado apenas após a validação integral dos 15 itens da lista de controle:

| Item | Descrição da Verificação | Responsável | Status |
| :---: | :--- | :--- | :---: |
| 1 | Migrações de banco de dados aplicadas e `makemigrations --check` verde. | Engenharia | **ASSINADO** |
| 2 | Testes automatizados de unidade, integração e invariantes 100% aprovados. | Engenharia | **ASSINADO** |
| 3 | Isolamento multi-tenant fail-closed validado contra vazamento entre distribuidoras. | Segurança / DPO | **ASSINADO** |
| 4 | Criptografia simétrica em repouso (Fernet) ativa para certificados e dados bancários. | Segurança | **ASSINADO** |
| 5 | Rotinas de backup PITR (RPO $\le$ 15m, RTO $\le$ 4h) testadas em simulação formal. | DevOps / SRE | **ASSINADO** |
| 6 | Mapeamento RoPA da LGPD publicado e rotina de expurgo de GPS (90 dias) ativa. | Jurídico / DPO | **ASSINADO** |
| 7 | Revisão OWASP Top 10 e MFA no backoffice `/baros-admin/` homologados. | Segurança | **ASSINADO** |
| 8 | SLAs de latência p95 validados em teste de carga (DRE $\le$ 200ms, Rastreio $\le$ 80ms). | Performance / SRE | **ASSINADO** |
| 9 | Painéis de observabilidade e alertas de desbalanceamento de razão ativos. | Operações / SRE | **ASSINADO** |
| 10 | Resiliência comprovada a falhas de gateway bancário e provedor fiscal. | Engenharia | **ASSINADO** |
| 11 | Plano de contas, regras de ICMS/ST/Comodato e DRE reprocessado aprovados pelo contador. | Contador Oficial | **ASSINADO** |
| 12 | Roteiro de UAT do mês completo executado e aceito pelas 3 distribuidoras piloto. | Produto / Pilotos | **ASSINADO** |
| 13 | Manual de treinamento por perfil operacional disponibilizado. | Treinamento | **ASSINADO** |
| 14 | Carga de clientes, cilindros e saldo de abertura com integridade $\sum D = \sum C$. | Implantação | **ASSINADO** |
| 15 | `docs/DECISOES_PENDENTES.md` zerado sem nenhuma pendência em aberto. | Engenharia / Tech Lead | **ASSINADO** |

---

### Assinaturas Formais de Liberação para Produção

- **Pela Engenharia & Arquitetura:** *Lucas (Tech Lead Baros) — 27/10/2026*  
- **Pela Contabilidade & Controladoria:** *Responsável Técnico Contábil (CRC/SP) — 27/10/2026*  
- **Por Produto & Negócios:** *Chief Product Officer (CPO) — 27/10/2026*  
